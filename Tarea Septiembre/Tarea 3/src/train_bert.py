"""Paso 8 — BERT como regresor (Persona 2): ajuste fino con ``num_labels=1``, pérdida MSE (o Huber) y early stopping.

  * Target escalado: y/TARGET_CAP en [0, 1]; la predicción se desescala y se recorta a [0, TARGET_CAP].
  * Texto largo: ``--truncation head`` (primeros max_len tokens) o ``head_tail`` (cabeza + cola). En PopResume el CV más
    largo mide 163 tokens, así que con max_len=256 NINGÚN CV se trunca y ambas estrategias son idénticas
    (ver ``token_length_report`` en el JSON de salida).
  * Early stopping sobre el MAE de validación en años (``--patience`` épocas sin mejorar); se conserva el mejor estado.
  * Solo se entrena con train; val elige la época; el test no se usa hasta ``src.evaluation``.

Salidas (por ``--tag``, por defecto el nombre del modelo + pérdida):
  models/bert/{tag}/                         pesos + tokenizador (no se versiona)
  output/predictions/bert_{tag}__{fuente}.csv   fuente ∈ {ocr, reference}
  output/metrics/bert_{tag}_report.json      hiperparámetros, tiempo, hardware, curva de entrenamiento

Uso (desde Tarea 3/):  python -m src.train_bert --model distilbert-base-uncased --epochs 8
"""
from __future__ import annotations

import argparse
import json
import platform
import time

import numpy as np
import pandas as pd
import torch
from torch import nn
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from src import model_common as M
from src import utils as U


def encode(tokenizer, texts, max_len: int, truncation: str):
    """Tokeniza con 'head' (corta el final) o 'head_tail' (conserva inicio y final del CV)."""
    if truncation == "head":
        return tokenizer(list(texts), truncation=True, max_length=max_len)["input_ids"]
    ids_all = tokenizer(list(texts), add_special_tokens=False)["input_ids"]
    budget = max_len - tokenizer.num_special_tokens_to_add()
    out = []
    for ids in ids_all:
        if len(ids) > budget:
            head = budget // 2
            ids = ids[:head] + ids[-(budget - head):]
        out.append(tokenizer.build_inputs_with_special_tokens(ids))
    return out


def collate(batch_ids, pad_id: int):
    n = max(len(x) for x in batch_ids)
    ids = torch.full((len(batch_ids), n), pad_id, dtype=torch.long)
    mask = torch.zeros((len(batch_ids), n), dtype=torch.long)
    for i, x in enumerate(batch_ids):
        ids[i, :len(x)] = torch.tensor(x)
        mask[i, :len(x)] = 1
    return ids, mask


@torch.no_grad()
def predict_ids(model, all_ids, pad_id: int, batch_size: int = 64) -> np.ndarray:
    model.eval()
    order = np.argsort([len(x) for x in all_ids])  # agrupa longitudes similares → menos padding
    out = np.zeros(len(all_ids))
    for s in range(0, len(order), batch_size):
        idx = order[s:s + batch_size]
        ids, mask = collate([all_ids[i] for i in idx], pad_id)
        out[idx] = model(input_ids=ids, attention_mask=mask).logits.squeeze(-1).float().numpy()
    return M.clip_target(out * U.TARGET_CAP)


class BertRegressor:
    """Predictor con la interfaz común ``predict(list[str])`` para evaluar/perturbar un BERT ya entrenado."""

    def __init__(self, path, max_len: int = 256, truncation: str = "head"):
        self.tokenizer = AutoTokenizer.from_pretrained(path)
        self.model = AutoModelForSequenceClassification.from_pretrained(path).eval()
        self.max_len, self.truncation = max_len, truncation

    def predict(self, texts) -> np.ndarray:
        ids = encode(self.tokenizer, texts, self.max_len, self.truncation)
        return predict_ids(self.model, ids, self.tokenizer.pad_token_id)


def hardware() -> dict:
    return {"cpu": platform.processor(), "platform": platform.platform(), "torch": torch.__version__,
            "cuda": torch.cuda.is_available(), "threads": torch.get_num_threads()}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default="distilbert-base-uncased")
    ap.add_argument("--loss", choices=["mse", "huber"], default="mse")
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--patience", type=int, default=3)
    ap.add_argument("--lr", type=float, default=5e-5)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--max-len", type=int, default=256)
    ap.add_argument("--truncation", choices=["head", "head_tail"], default="head")
    ap.add_argument("--source", choices=["ocr", "ocr_raw"], default="ocr", help="texto de entrenamiento (limpieza)")
    ap.add_argument("--n-train", type=int, default=0, help="submuestra de train para pruebas rápidas")
    ap.add_argument("--tag", default=None)
    args = ap.parse_args(argv)

    tag = args.tag or f"{args.model.split('/')[-1]}_{args.loss}"
    U.ensure_dirs(); U.PREDICTIONS_DIR.mkdir(parents=True, exist_ok=True)
    U.set_all_seeds()
    torch.set_num_threads(max(1, torch.get_num_threads()))

    tok = AutoTokenizer.from_pretrained(args.model)
    data = M.load_all(args.source)
    train, val = data["train"], data["val"]
    if args.n_train:
        train = train.sample(args.n_train, random_state=U.RANDOM_SEED).reset_index(drop=True)

    x_tr = encode(tok, train["text"], args.max_len, args.truncation)
    x_va = encode(tok, val["text"], args.max_len, args.truncation)
    lens = [len(x) for x in x_tr + x_va]
    len_report = {"mean": float(np.mean(lens)), "max": int(max(lens)),
                  "pct_over_max_len_before_truncation": float(np.mean([len(tok(t)["input_ids"]) > args.max_len
                                                                          for t in train["text"]]))}
    y_tr = torch.tensor(train["exp_year"].values / U.TARGET_CAP, dtype=torch.float32)

    model = AutoModelForSequenceClassification.from_pretrained(args.model, num_labels=1)
    loss_fn = nn.MSELoss() if args.loss == "mse" else nn.HuberLoss(delta=0.1)  # 0.1 = 2 años en escala /20
    steps = args.epochs * int(np.ceil(len(x_tr) / args.batch_size))
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.01)
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: min((s + 1) / max(1, int(0.1 * steps)), max(0.0, (steps - s) / max(1, steps - int(0.1 * steps)))))

    rng = np.random.default_rng(U.RANDOM_SEED)
    history, best_mae, best_epoch, bad = [], np.inf, -1, 0
    out_dir = U.BERT_DIR / tag
    t_start = time.perf_counter()
    for epoch in range(1, args.epochs + 1):
        model.train()
        perm = rng.permutation(len(x_tr))
        tot, t0 = 0.0, time.perf_counter()
        for s in range(0, len(perm), args.batch_size):
            idx = perm[s:s + args.batch_size]
            ids, mask = collate([x_tr[i] for i in idx], tok.pad_token_id)
            pred = model(input_ids=ids, attention_mask=mask).logits.squeeze(-1)
            loss = loss_fn(pred, y_tr[idx])
            opt.zero_grad(); loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step(); sched.step()
            tot += loss.item() * len(idx)
        val_pred = predict_ids(model, x_va, tok.pad_token_id)
        val_mae = float(np.abs(val_pred - val["exp_year"].values).mean())
        history.append({"epoch": epoch, "train_loss": tot / len(perm), "val_MAE": val_mae,
                        "epoch_seconds": round(time.perf_counter() - t0, 1)})
        print(history[-1], flush=True)
        if val_mae < best_mae - 1e-4:
            best_mae, best_epoch, bad = val_mae, epoch, 0
            model.save_pretrained(out_dir); tok.save_pretrained(out_dir)
        else:
            bad += 1
            if bad >= args.patience:
                print(f"early stopping en la época {epoch} (mejor: {best_epoch})")
                break
    train_seconds = time.perf_counter() - t_start

    best = BertRegressor(out_dir, args.max_len, args.truncation)
    for source in ("ocr", "reference"):
        rows = []
        for split, df in (("val", M.load_split("val", source)), ("test", M.load_split("test", source))):
            rows.append(pd.DataFrame({"id": df["id"], "split": split, "occupation": df["occupation"],
                                      "y_true": df["exp_year"], "y_pred": best.predict(df["text"].tolist())}))
        pd.concat(rows).to_csv(U.PREDICTIONS_DIR / f"bert_{tag}__{source}.csv", index=False)

    report = {"tag": tag, "args": vars(args), "best_epoch": best_epoch, "best_val_MAE": best_mae,
              "train_seconds": round(train_seconds, 1), "hardware": hardware(),
              "token_length_report": len_report, "history": history,
              "params_millions": round(sum(p.numel() for p in model.parameters()) / 1e6, 1)}
    (U.METRICS_DIR / f"bert_{tag}_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"listo: {tag} mejor época {best_epoch} val_MAE={best_mae:.3f} en {train_seconds/60:.1f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
