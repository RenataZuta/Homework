"""Automatización Selenium del formulario PeopleSync (Homework1).

Notas de diseño:
- Los <select> de área/puesto/contrato/sede no declaran atributo value, así
  que su value es igual al texto visible; select_by_visible_text funciona
  directamente con los datos del CSV.
- Los radio de "modalidad" están ocultos con opacity:0 (estilo "pill"), por lo
  que se hace click en el <span> visible hermano en vez del <input>, evitando
  ElementNotInteractableException.
- Los <input type="date"> se llenan escribiendo su .value en formato ISO
  (AAAA-MM-DD) vía JavaScript y disparando eventos input/change. send_keys()
  en inputs de fecha depende del locale/orden de tabulación del navegador y es
  frágil; setear el value directamente es la forma fiable de hacerlo.
"""

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

from . import config
from .validators import parse_fecha


class PeopleSyncBot:
    def __init__(self, headless=None, timeout=None):
        self.timeout = timeout or config.TIMEOUT_SEGUNDOS

        opciones = Options()
        usar_headless = config.HEADLESS if headless is None else headless
        if usar_headless:
            opciones.add_argument("--headless=new")
        opciones.add_argument("--window-size=1400,1000")

        self.driver = webdriver.Chrome(options=opciones)
        self.wait = WebDriverWait(self.driver, self.timeout)

    def abrir(self):
        self.driver.get(config.FORM_URL)
        self.wait.until(EC.presence_of_element_located((By.ID, "btn-registrar")))

    def cerrar(self):
        self.driver.quit()

    # -- helpers de llenado ------------------------------------------------

    def _set_texto(self, elemento_id, valor):
        campo = self.wait.until(EC.presence_of_element_located((By.ID, elemento_id)))
        campo.clear()
        campo.send_keys(valor)

    def _set_fecha(self, elemento_id, valor_iso):
        campo = self.driver.find_element(By.ID, elemento_id)
        self.driver.execute_script(
            "arguments[0].value = arguments[1];"
            "arguments[0].dispatchEvent(new Event('input', {bubbles: true}));"
            "arguments[0].dispatchEvent(new Event('change', {bubbles: true}));",
            campo, valor_iso,
        )

    def _set_select(self, elemento_id, valor):
        Select(self.driver.find_element(By.ID, elemento_id)).select_by_visible_text(valor)

    def _set_radio(self, valor):
        # click() nativo (por coordenadas) puede fallar con
        # ElementClickInterceptedException si el radio quedó parcialmente
        # tapado por el scroll suave que dispara limpiarFormulario() tras el
        # registro anterior. Un click disparado por JS evita ese problema.
        xpath = f"//input[@name='modalidad' and @value='{valor}']"
        radio = self.driver.find_element(By.XPATH, xpath)
        self.driver.execute_script("arguments[0].click();", radio)

    def _contar_filas(self):
        return len(self.driver.find_elements(By.CSS_SELECTOR, "#tabla-body tr"))

    # -- operación principal -------------------------------------------------

    def registrar_empleado(self, registro):
        """Llena el formulario con `registro`, envía y verifica que haya
        aparecido en la tabla de registros de la sesión.
        Devuelve (True, None) si se verificó el alta, o (False, motivo)."""
        filas_antes = self._contar_filas()

        self._set_texto("nombres", registro["nombres"])
        self._set_texto("dni", registro["dni"])
        self._set_fecha("fecha_nacimiento", parse_fecha(registro["fecha_nacimiento"]))
        self._set_select("genero", registro["genero"])
        self._set_texto("telefono", registro["telefono"])
        self._set_texto("correo", registro["correo"])
        self._set_select("area", registro["area"])
        self._set_select("puesto", registro["puesto"])
        self._set_select("contrato", registro["contrato"])
        self._set_select("sede", registro["sede"])
        self._set_fecha("fecha_ingreso", parse_fecha(registro["fecha_ingreso"]))
        self._set_radio(registro["modalidad"])

        # click() vía JS por la misma razón que en _set_radio: evita
        # ElementClickInterceptedException si el botón quedó momentáneamente
        # tapado por el toast de alerta o el scroll suave del registro previo.
        boton = self.driver.find_element(By.ID, "btn-registrar")
        self.driver.execute_script("arguments[0].click();", boton)

        try:
            self.wait.until(lambda d: self._contar_filas() > filas_antes)
        except TimeoutException:
            errores_visibles = [
                e.text for e in self.driver.find_elements(By.CSS_SELECTOR, ".field-error.show") if e.text
            ]
            motivo = "El formulario no confirmó el registro dentro del tiempo de espera."
            if errores_visibles:
                motivo += " Errores mostrados en pantalla: " + "; ".join(errores_visibles)
            return False, motivo

        ultima_fila = self.driver.find_elements(By.CSS_SELECTOR, "#tabla-body tr")[-1]
        dni_en_tabla = ultima_fila.find_elements(By.TAG_NAME, "td")[1].text
        if dni_en_tabla != registro["dni"]:
            return False, (
                f"La última fila de la tabla no corresponde al DNI enviado "
                f"(tabla={dni_en_tabla}, esperado={registro['dni']})"
            )

        return True, None
