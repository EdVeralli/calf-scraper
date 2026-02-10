"""
Scraper para CALF - Portal de Clientes
(Cooperativa de Agua, Luz y Fuerza de Neuquen)

Obtiene cuentas de energia y detalle de cada cuenta.

Uso:
    python calf_scraper.py                (navegador visible, reporte consola + CSV)
    python calf_scraper.py --headless     (sin abrir navegador)
    python calf_scraper.py --json         (salida en formato JSON)
"""

import time
import re
import json
import csv
import sys
import os
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional
from pathlib import Path

from dotenv import load_dotenv
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# ============================================================
# CONFIGURACION
# ============================================================
env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)

URL = "https://sixon.com.ar/PortalClientes_CALF_PROD/com.portalclientes.portalloginsinregistro"
TIPO_ID = os.getenv("CALF_TIPO_ID", "4")   # 1=DNI, 2=CUIT, 4=SOCIO
NRO_ID = os.getenv("CALF_NRO_ID")

if not NRO_ID:
    print("ERROR: Falta CALF_NRO_ID en archivo .env")
    sys.exit(1)

CAPTCHA_TIMEOUT = 120  # segundos para resolver captcha
DEBUG_DIR = Path(__file__).parent / "debug"

# ============================================================
# MODELOS DE DATOS
# ============================================================
@dataclass
class Cuenta:
    nro: int
    servicio: str
    domicilio: str
    estado: str
    detalle: Dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


@dataclass
class Persona:
    usuario: str
    persona_id: str
    nombre: str
    cuentas: List[Cuenta] = field(default_factory=list)

    def to_dict(self):
        return {
            'usuario': self.usuario,
            'persona_id': self.persona_id,
            'nombre': self.nombre,
            'cuentas': [c.to_dict() for c in self.cuentas]
        }


# ============================================================
# FUNCIONES AUXILIARES
# ============================================================
def timestamp() -> str:
    return datetime.now().strftime('%H:%M:%S')


def guardar_debug(driver, nombre: str):
    """Guarda screenshot y HTML para debug"""
    DEBUG_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    try:
        driver.save_screenshot(str(DEBUG_DIR / f"{nombre}_{ts}.png"))
        html_path = DEBUG_DIR / f"{nombre}_{ts}.html"
        html_path.write_text(driver.page_source, encoding='utf-8')
    except Exception as e:
        print(f"[{timestamp()}] WARN: No se pudo guardar debug: {e}")


# ============================================================
# DRIVER
# ============================================================
def crear_driver(headless: bool = False) -> uc.Chrome:
    """Crea driver con undetected-chromedriver"""
    options = uc.ChromeOptions()
    if headless:
        options.add_argument("--headless")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--log-level=3")

    driver = uc.Chrome(options=options)
    driver.implicitly_wait(10)
    return driver


# ============================================================
# LOGIN
# ============================================================
def login(driver: uc.Chrome) -> bool:
    """Realiza el login en el portal CALF"""
    print(f"[{timestamp()}] Accediendo al portal CALF...")
    driver.get(URL)

    wait = WebDriverWait(driver, 30)

    try:
        # Esperar que cargue el formulario
        wait.until(EC.presence_of_element_located((By.ID, 'vTIPOID')))
        print(f"[{timestamp()}] Formulario cargado")

        # Seleccionar tipo de ID
        tipo_select = Select(driver.find_element(By.ID, 'vTIPOID'))
        tipo_select.select_by_value(TIPO_ID)
        time.sleep(0.5)

        # Ingresar numero
        nro_field = driver.find_element(By.ID, 'vNROID')
        nro_field.clear()
        nro_field.send_keys(NRO_ID)

        tipo_nombres = {'1': 'DNI', '2': 'CUIT', '4': 'SOCIO'}
        print(f"[{timestamp()}] Tipo: {tipo_nombres.get(TIPO_ID, TIPO_ID)} | Numero: {NRO_ID}")

        # Esperar resolucion del reCAPTCHA
        if not esperar_captcha(driver):
            print(f"[{timestamp()}] ERROR: Timeout esperando captcha")
            guardar_debug(driver, "captcha_timeout")
            return False

        # Click en INICIAR SESION
        login_btn = driver.find_element(By.ID, 'LOGIN')
        login_btn.click()
        print(f"[{timestamp()}] Click en INICIAR SESION...")

        # Esperar que cargue la pagina post-login
        time.sleep(3)

        # Verificar login exitoso: buscar "Cuentas de la persona" o cambio de URL
        for _ in range(20):
            page_text = driver.find_element(By.TAG_NAME, 'body').text
            if 'Cuentas de la persona' in page_text:
                return True
            if 'Error' in page_text and 'robot' in page_text:
                print(f"[{timestamp()}] ERROR: El portal detecto robot. Captcha no resuelto.")
                guardar_debug(driver, "error_robot")
                return False
            time.sleep(1)

        # Ultimo intento: verificar si cambio la pagina
        if 'portalloginsinregistro' not in driver.current_url.lower():
            return True

        print(f"[{timestamp()}] ERROR: No se detecto pagina post-login")
        guardar_debug(driver, "login_fallido")
        return False

    except TimeoutException:
        print(f"[{timestamp()}] ERROR: Timeout durante login")
        guardar_debug(driver, "login_timeout")
        return False
    except Exception as e:
        print(f"[{timestamp()}] ERROR: {e}")
        guardar_debug(driver, "login_error")
        return False


def esperar_captcha(driver: uc.Chrome) -> bool:
    """Espera que el reCAPTCHA sea resuelto (automatica o manualmente)"""
    print(f"[{timestamp()}] Esperando resolucion de reCAPTCHA...")

    inicio = time.time()
    avisado = False

    while time.time() - inicio < CAPTCHA_TIMEOUT:
        try:
            response = driver.find_element(By.ID, 'g-recaptcha-response')
            valor = response.get_attribute('value')
            if valor and len(valor) > 10:
                print(f"[{timestamp()}] reCAPTCHA resuelto!")
                return True
        except NoSuchElementException:
            # Si no hay captcha, quizas undetected-chromedriver lo evito
            return True

        if not avisado and time.time() - inicio > 5:
            print(f"[{timestamp()}] >> Resuelve el captcha en el navegador (timeout: {CAPTCHA_TIMEOUT}s)")
            avisado = True

        time.sleep(2)

    return False


# ============================================================
# EXTRACCION DE DATOS
# ============================================================
def extraer_persona(driver: uc.Chrome) -> Persona:
    """Extrae informacion de la persona y sus cuentas"""
    print(f"[{timestamp()}] Extrayendo datos de la persona...")

    usuario = ""
    persona_id = ""
    nombre = ""

    try:
        page_text = driver.find_element(By.TAG_NAME, 'body').text
        lineas = page_text.split('\n')

        for i, linea in enumerate(lineas):
            linea_clean = linea.strip()

            if 'USUARIO' in linea_clean.upper():
                # El valor puede estar en la misma linea o la siguiente
                match = re.search(r'(\d{10,})', linea_clean)
                if match:
                    usuario = match.group(1)
                elif i + 1 < len(lineas):
                    match = re.search(r'(\d{10,})', lineas[i + 1])
                    if match:
                        usuario = match.group(1)

            if 'PERSONA' in linea_clean.upper() and 'CUENTAS' not in linea_clean.upper():
                match = re.search(r'(\d+)', linea_clean.replace(usuario, ''))
                if match:
                    persona_id = match.group(1)
                elif i + 1 < len(lineas):
                    match = re.search(r'(\d+)', lineas[i + 1])
                    if match:
                        persona_id = match.group(1)

            if 'NOMBRE' in linea_clean.upper():
                # El nombre viene despues de "NOMBRE"
                nombre_match = re.sub(r'^.*NOMBRE\s*', '', linea_clean, flags=re.IGNORECASE)
                if nombre_match.strip():
                    nombre = nombre_match.strip()
                elif i + 1 < len(lineas):
                    nombre = lineas[i + 1].strip()

    except Exception as e:
        print(f"[{timestamp()}] WARN: Error extrayendo info persona: {e}")

    # Extraer cuentas de la tabla
    cuentas = extraer_cuentas_tabla(driver)

    persona = Persona(
        usuario=usuario,
        persona_id=persona_id,
        nombre=nombre,
        cuentas=cuentas
    )

    print(f"[{timestamp()}] Persona: {nombre} | Cuentas: {len(cuentas)}")
    return persona


def extraer_cuentas_tabla(driver: uc.Chrome) -> List[Cuenta]:
    """Extrae las cuentas de la tabla de la pagina post-login"""
    cuentas = []

    try:
        # La tabla de GeneXus puede ser un <table> o divs con grid
        # Intentar encontrar filas de tabla
        filas = driver.find_elements(By.CSS_SELECTOR, 'table tr')

        # Filtrar filas de datos (excluir header)
        filas_datos = []
        for fila in filas:
            celdas = fila.find_elements(By.TAG_NAME, 'td')
            if len(celdas) >= 3:
                filas_datos.append(fila)

        for fila in filas_datos:
            celdas = fila.find_elements(By.TAG_NAME, 'td')
            textos = [c.text.strip() for c in celdas]

            # Formato esperado: [Cta, Servicio, Domicilio, Estado, ...]
            if len(textos) >= 4:
                try:
                    nro = int(textos[0]) if textos[0].isdigit() else 0
                except ValueError:
                    nro = 0

                cuenta = Cuenta(
                    nro=nro,
                    servicio=textos[1],
                    domicilio=textos[2],
                    estado=textos[3]
                )
                cuentas.append(cuenta)

        if not cuentas:
            # Fallback: intentar parsear del texto de la pagina
            cuentas = extraer_cuentas_texto(driver)

    except Exception as e:
        print(f"[{timestamp()}] WARN: Error extrayendo tabla de cuentas: {e}")
        cuentas = extraer_cuentas_texto(driver)

    return cuentas


def extraer_cuentas_texto(driver: uc.Chrome) -> List[Cuenta]:
    """Fallback: extraer cuentas del texto plano de la pagina"""
    cuentas = []
    try:
        body_text = driver.find_element(By.TAG_NAME, 'body').text
        # Buscar patron: numero + Energia + direccion + estado
        patron = re.compile(
            r'(\d+)\s+'
            r'(Energ[ií]a|Gas|Agua)\s+'
            r'(.+?)\s+'
            r'(CONECTADO|DESCONECTADO|ACTIVO|INACTIVO|SUSPENDIDO)',
            re.IGNORECASE
        )
        for match in patron.finditer(body_text):
            cuenta = Cuenta(
                nro=int(match.group(1)),
                servicio=match.group(2),
                domicilio=match.group(3).strip(),
                estado=match.group(4).upper()
            )
            cuentas.append(cuenta)
    except Exception:
        pass
    return cuentas


def extraer_detalle_cuenta(driver: uc.Chrome, cuenta: Cuenta, indice: int) -> Dict:
    """Entra al detalle de una cuenta y extrae la info disponible"""
    detalle = {}

    try:
        print(f"[{timestamp()}] Entrando al detalle de cuenta {cuenta.nro} ({cuenta.domicilio})...")

        # Buscar el boton/icono de detalle en la fila correspondiente
        filas = driver.find_elements(By.CSS_SELECTOR, 'table tr')
        fila_target = None

        for fila in filas:
            celdas = fila.find_elements(By.TAG_NAME, 'td')
            if celdas and celdas[0].text.strip() == str(cuenta.nro):
                fila_target = fila
                break

        if not fila_target:
            # Intentar por indice
            filas_datos = [f for f in filas if f.find_elements(By.TAG_NAME, 'td')]
            if indice < len(filas_datos):
                fila_target = filas_datos[indice]

        if fila_target:
            # Buscar link o boton clickeable en la fila
            clickeable = (
                fila_target.find_elements(By.TAG_NAME, 'a') or
                fila_target.find_elements(By.CSS_SELECTOR, 'input[type="image"], input[type="button"]') or
                fila_target.find_elements(By.CSS_SELECTOR, 'img[onclick], span[onclick]')
            )

            if clickeable:
                clickeable[0].click()
                time.sleep(4)

                # Extraer todo el contenido de la pagina de detalle
                detalle = parsear_pagina_detalle(driver)

                # Volver a la lista de cuentas
                volver_a_cuentas(driver)
            else:
                print(f"[{timestamp()}] WARN: No se encontro boton de detalle para cuenta {cuenta.nro}")
        else:
            print(f"[{timestamp()}] WARN: No se encontro fila para cuenta {cuenta.nro}")

    except Exception as e:
        print(f"[{timestamp()}] ERROR extrayendo detalle cuenta {cuenta.nro}: {e}")
        guardar_debug(driver, f"detalle_cuenta_{cuenta.nro}")

    return detalle


def parsear_pagina_detalle(driver: uc.Chrome) -> Dict:
    """Parsea la pagina de detalle de una cuenta, extrayendo toda la info disponible"""
    detalle = {}

    try:
        time.sleep(2)
        body_text = driver.find_element(By.TAG_NAME, 'body').text

        # Guardar texto completo para referencia
        detalle['texto_completo'] = body_text

        # Extraer pares clave-valor comunes
        patrones = {
            'suministro': r'(?:SUMINISTRO|Suministro|N[°º]\s*Suministro)\s*[:\s]*(\S+)',
            'medidor': r'(?:MEDIDOR|Medidor|N[°º]\s*Medidor)\s*[:\s]*(\S+)',
            'tarifa': r'(?:TARIFA|Tarifa|Categoria)\s*[:\s]*(.+?)(?:\n|$)',
            'estado': r'(?:ESTADO|Estado)\s*[:\s]*(\S+)',
            'direccion': r'(?:DIRECCI[OÓ]N|Direcci[oó]n|Domicilio)\s*[:\s]*(.+?)(?:\n|$)',
            'localidad': r'(?:LOCALIDAD|Localidad|Ciudad)\s*[:\s]*(.+?)(?:\n|$)',
            'ultima_lectura': r'(?:[UÚ]ltima\s*Lectura|LECTURA)\s*[:\s]*(.+?)(?:\n|$)',
            'proximo_vencimiento': r'(?:Pr[oó]ximo\s*Vencimiento|VENCIMIENTO)\s*[:\s]*(.+?)(?:\n|$)',
        }

        for key, patron in patrones.items():
            match = re.search(patron, body_text, re.IGNORECASE)
            if match:
                detalle[key] = match.group(1).strip()

        # Buscar importes/deuda
        importes = re.findall(r'\$\s*[\d.,]+', body_text)
        if importes:
            detalle['importes_encontrados'] = importes

        # Buscar tablas de detalle (facturas, consumos, etc.)
        tablas = driver.find_elements(By.TAG_NAME, 'table')
        for idx, tabla in enumerate(tablas):
            filas = tabla.find_elements(By.TAG_NAME, 'tr')
            if len(filas) > 1:  # tabla con datos
                tabla_data = []
                headers = []

                # Extraer headers
                ths = filas[0].find_elements(By.TAG_NAME, 'th')
                if ths:
                    headers = [th.text.strip() for th in ths]

                # Extraer filas de datos
                for fila in filas:
                    celdas = fila.find_elements(By.TAG_NAME, 'td')
                    if celdas:
                        fila_data = [c.text.strip() for c in celdas]
                        if any(fila_data):  # ignorar filas vacias
                            if headers and len(headers) == len(fila_data):
                                tabla_data.append(dict(zip(headers, fila_data)))
                            else:
                                tabla_data.append(fila_data)

                if tabla_data:
                    detalle[f'tabla_{idx}'] = tabla_data

        # Limpiar texto_completo si hay otros datos
        if len(detalle) > 1:
            del detalle['texto_completo']

    except Exception as e:
        detalle['error'] = str(e)

    return detalle


def volver_a_cuentas(driver: uc.Chrome):
    """Intenta volver a la pagina de cuentas"""
    try:
        # Buscar link/boton de volver
        volver = (
            driver.find_elements(By.XPATH, "//a[contains(text(),'Volver')]") or
            driver.find_elements(By.XPATH, "//input[contains(@value,'Volver')]") or
            driver.find_elements(By.XPATH, "//a[contains(text(),'Cuentas')]")
        )
        if volver:
            volver[0].click()
            time.sleep(3)
            return

        # Fallback: navegar atras
        driver.back()
        time.sleep(3)

        # Verificar que estamos en la pagina de cuentas
        body = driver.find_element(By.TAG_NAME, 'body').text
        if 'Cuentas de la persona' not in body:
            driver.back()
            time.sleep(3)

    except Exception:
        driver.back()
        time.sleep(3)


# ============================================================
# REPORTE
# ============================================================
def imprimir_reporte(persona: Persona):
    """Imprime un reporte formateado"""
    print("\n" + "=" * 70)
    print("            REPORTE DE CUENTAS - CALF ENERGIA")
    print("=" * 70)
    print(f"Fecha del reporte: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"Nombre: {persona.nombre}")
    print(f"Usuario: {persona.usuario}")
    print(f"Persona: {persona.persona_id}")
    print("=" * 70)

    if not persona.cuentas:
        print("\n  No se encontraron cuentas.")
        print("=" * 70)
        return

    print(f"\nCuentas encontradas: {len(persona.cuentas)}\n")
    print(f"{'Cta':>4}  {'Servicio':<10}  {'Domicilio':<40}  {'Estado':<15}")
    print("-" * 75)

    for c in persona.cuentas:
        print(f"{c.nro:>4}  {c.servicio:<10}  {c.domicilio:<40}  {c.estado:<15}")

    # Detalle de cada cuenta
    for c in persona.cuentas:
        if c.detalle:
            print(f"\n{'─' * 70}")
            print(f"  DETALLE CUENTA {c.nro} - {c.domicilio}")
            print(f"{'─' * 70}")
            for key, valor in c.detalle.items():
                if key.startswith('tabla_'):
                    print(f"\n  {key}:")
                    if isinstance(valor, list):
                        for item in valor:
                            if isinstance(item, dict):
                                for k, v in item.items():
                                    print(f"    {k}: {v}")
                                print()
                            else:
                                print(f"    {item}")
                else:
                    print(f"  {key}: {valor}")

    print("\n" + "=" * 70)


# ============================================================
# EXPORTAR CSV
# ============================================================
def exportar_csv(persona: Persona, archivo: str):
    """Exporta los datos a CSV"""
    ruta = Path(archivo)

    with open(ruta, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f, delimiter=';')

        # --- SECCION: PERSONA ---
        w.writerow(['DATOS DE LA PERSONA'])
        w.writerow(['Campo', 'Valor'])
        w.writerow(['Nombre', persona.nombre])
        w.writerow(['Usuario', persona.usuario])
        w.writerow(['Persona ID', persona.persona_id])
        w.writerow([])

        # --- SECCION: CUENTAS ---
        w.writerow(['CUENTAS'])
        w.writerow(['Nro', 'Servicio', 'Domicilio', 'Estado'])
        for c in persona.cuentas:
            w.writerow([c.nro, c.servicio, c.domicilio, c.estado])
        w.writerow([])

        # --- SECCION: DETALLE POR CUENTA ---
        for c in persona.cuentas:
            if c.detalle:
                w.writerow([f'DETALLE CUENTA {c.nro} - {c.domicilio}'])
                for key, valor in c.detalle.items():
                    if key.startswith('tabla_') and isinstance(valor, list):
                        # Escribir tabla
                        w.writerow([f'  {key}'])
                        for item in valor:
                            if isinstance(item, dict):
                                if not any(k == list(item.keys())[0] for row in [] for k in row):
                                    w.writerow(list(item.keys()))
                                w.writerow(list(item.values()))
                            elif isinstance(item, list):
                                w.writerow(item)
                    elif key == 'importes_encontrados' and isinstance(valor, list):
                        w.writerow([key, ' | '.join(valor)])
                    else:
                        w.writerow([key, valor])
                w.writerow([])

    print(f"[{timestamp()}] CSV exportado: {ruta.resolve()}")


# ============================================================
# MAIN
# ============================================================
def main():
    headless = '--headless' in sys.argv
    output_json = '--json' in sys.argv

    # CSV: siempre se genera, nombre basado en el NRO_ID
    csv_archivo = f'calf_{TIPO_ID}_{NRO_ID}.csv'

    if not output_json:
        print("\n" + "=" * 70)
        print("         SCRAPER CALF - PORTAL DE CLIENTES")
        print("=" * 70 + "\n")

    driver = None
    try:
        driver = crear_driver(headless=headless)

        # Login
        if not login(driver):
            print("ERROR: No se pudo completar el login")
            sys.exit(1)

        print(f"[{timestamp()}] Login exitoso")

        # Extraer persona y cuentas
        persona = extraer_persona(driver)

        # Extraer detalle de cada cuenta
        for i, cuenta in enumerate(persona.cuentas):
            detalle = extraer_detalle_cuenta(driver, cuenta, i)
            cuenta.detalle = detalle

        # Output
        if output_json:
            print(json.dumps(persona.to_dict(), indent=2, ensure_ascii=False))
        else:
            imprimir_reporte(persona)

        # CSV se genera siempre
        exportar_csv(persona, csv_archivo)

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        if driver:
            guardar_debug(driver, "error_general")
        sys.exit(1)
    finally:
        if driver:
            driver.quit()


if __name__ == "__main__":
    main()
