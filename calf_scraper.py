"""
Scraper para CALF - Portal de Clientes
(Cooperativa de Agua, Luz y Fuerza de Neuquen)

Obtiene cuentas de energia y detalle de cada cuenta.
Resuelve reCAPTCHA automaticamente via CapSolver.

Uso:
    python calf_scraper.py                (headless, automatico)
    python calf_scraper.py --no-headless  (navegador visible, para debug)
    python calf_scraper.py --json         (salida en formato JSON)
"""

import time
import re
import json
import csv
import sys
import os
import requests
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional
from pathlib import Path

from dotenv import load_dotenv
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# ============================================================
# CONFIGURACION
# ============================================================
env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)

URL = "https://sixon.com.ar/PortalClientes_CALF_PROD/servlet/com.portalclientes.portalloginsinregistro"
TIPO_ID = os.getenv("CALF_TIPO_ID", "4")   # 1=DNI, 2=CUIT, 4=SOCIO
NRO_ID = os.getenv("CALF_NRO_ID")
CAPSOLVER_API_KEY = os.getenv("CAPSOLVER_API_KEY")
RECAPTCHA_SITE_KEY = "6LeIPuYUAAAAAP4Z8B95v28B1rJWz_kPxmhiO4tc"

if not NRO_ID:
    print("ERROR: Falta CALF_NRO_ID en archivo .env")
    sys.exit(1)

if not CAPSOLVER_API_KEY:
    print("ERROR: Falta CAPSOLVER_API_KEY en archivo .env")
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
    """Crea driver con undetected-chromedriver y perfil persistente"""
    options = uc.ChromeOptions()
    if headless:
        options.add_argument("--headless")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--log-level=3")

    # Perfil persistente para mantener cookies del reCAPTCHA entre ejecuciones
    profile_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'chrome_profile')
    options.add_argument(f"--user-data-dir={profile_dir}")

    driver = uc.Chrome(options=options, version_main=144)
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
        time.sleep(3)
        print(f"[{timestamp()}] URL actual: {driver.current_url}")
        print(f"[{timestamp()}] Titulo: {driver.title}")
        wait.until(EC.presence_of_element_located((By.ID, 'vTIPOID')))
        print(f"[{timestamp()}] Formulario cargado")

        # Seleccionar tipo de ID
        tipo_select = Select(driver.find_element(By.ID, 'vTIPOID'))
        tipo_select.select_by_value(TIPO_ID)
        time.sleep(0.5)

        # Ingresar numero via JavaScript (GeneXus necesita eventos especificos)
        driver.execute_script(
            "var el = document.getElementById('vNROID');"
            "el.focus();"
            "el.value = arguments[0];"
            "el.dispatchEvent(new Event('input', {bubbles: true}));"
            "el.dispatchEvent(new Event('change', {bubbles: true}));"
            "el.blur();",
            NRO_ID
        )
        time.sleep(0.5)
        # Verificar
        valor_actual = driver.find_element(By.ID, 'vNROID').get_attribute('value')
        if valor_actual != NRO_ID:
            # Fallback: click y tipear
            nro_field = driver.find_element(By.ID, 'vNROID')
            nro_field.click()
            nro_field.send_keys(Keys.CONTROL, 'a')
            nro_field.send_keys(NRO_ID)
            print(f"[{timestamp()}] Numero cargado via send_keys (fallback)")
        else:
            print(f"[{timestamp()}] Numero cargado: {valor_actual}")

        tipo_nombres = {'1': 'DNI', '2': 'CUIT', '4': 'SOCIO'}
        print(f"[{timestamp()}] Tipo: {tipo_nombres.get(TIPO_ID, TIPO_ID)} | Numero: {NRO_ID}")

        # Esperar resolucion del reCAPTCHA
        if not esperar_captcha(driver):
            print(f"[{timestamp()}] ERROR: Timeout esperando captcha")
            guardar_debug(driver, "captcha_timeout")
            return False

        # Si la pagina ya avanzo (usuario hizo login manual), no hacer click
        page_text = driver.find_element(By.TAG_NAME, 'body').text
        if 'Cuentas de la persona' in page_text:
            print(f"[{timestamp()}] Login ya completado manualmente")
            return True

        # Click en INICIAR SESION
        try:
            login_btn = driver.find_element(By.ID, 'LOGIN')
            login_btn.click()
            print(f"[{timestamp()}] Click en INICIAR SESION...")
        except NoSuchElementException:
            print(f"[{timestamp()}] Boton LOGIN no encontrado, pagina puede haber avanzado")

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
        print(f"[{timestamp()}] URL: {driver.current_url}")
        try:
            body = driver.find_element(By.TAG_NAME, 'body').text[:500]
            print(f"[{timestamp()}] Body: {body}")
        except:
            pass
        guardar_debug(driver, "login_timeout")
        return False
    except Exception as e:
        print(f"[{timestamp()}] ERROR: {e}")
        guardar_debug(driver, "login_error")
        return False


def resolver_captcha_capsolver() -> Optional[str]:
    """Resuelve reCAPTCHA v2 usando la API de CapSolver"""
    print(f"[{timestamp()}] Enviando reCAPTCHA a CapSolver...")

    # Paso 1: Crear tarea
    payload = {
        "clientKey": CAPSOLVER_API_KEY,
        "task": {
            "type": "ReCaptchaV2TaskProxyLess",
            "websiteURL": URL,
            "websiteKey": RECAPTCHA_SITE_KEY,
        }
    }

    try:
        resp = requests.post("https://api.capsolver.com/createTask", json=payload, timeout=30)
        data = resp.json()

        if data.get("errorId", 1) != 0:
            print(f"[{timestamp()}] ERROR CapSolver createTask: {data.get('errorDescription', data)}")
            return None

        task_id = data["taskId"]
        print(f"[{timestamp()}] Tarea creada: {task_id}")

    except Exception as e:
        print(f"[{timestamp()}] ERROR conectando a CapSolver: {e}")
        return None

    # Paso 2: Esperar resultado (polling)
    for intento in range(60):  # max ~120 seg
        time.sleep(2)
        try:
            resp = requests.post("https://api.capsolver.com/getTaskResult", json={
                "clientKey": CAPSOLVER_API_KEY,
                "taskId": task_id,
            }, timeout=30)
            result = resp.json()

            if result.get("status") == "ready":
                token = result["solution"]["gRecaptchaResponse"]
                print(f"[{timestamp()}] reCAPTCHA resuelto por CapSolver! (token: {token[:50]}...)")
                return token

            if result.get("errorId", 0) != 0:
                print(f"[{timestamp()}] ERROR CapSolver: {result.get('errorDescription', result)}")
                return None

            # Aun procesando
            if intento % 5 == 0:
                print(f"[{timestamp()}] Esperando respuesta de CapSolver... ({intento * 2}s)")

        except Exception as e:
            print(f"[{timestamp()}] ERROR polling CapSolver: {e}")

    print(f"[{timestamp()}] ERROR: Timeout esperando respuesta de CapSolver")
    return None


def esperar_captcha(driver: uc.Chrome) -> bool:
    """Resuelve el reCAPTCHA usando CapSolver y lo inyecta en la pagina"""
    print(f"[{timestamp()}] Resolviendo reCAPTCHA con CapSolver...")

    token = resolver_captcha_capsolver()
    if not token:
        print(f"[{timestamp()}] ERROR: No se pudo resolver el captcha")
        return False

    # Inyectar el token en la pagina
    try:
        # Buscar el textarea g-recaptcha-response (puede estar oculto o no existir aun)
        driver.execute_script("""
            var token = arguments[0];
            // Buscar textarea existente
            var ta = document.querySelector('textarea[name="g-recaptcha-response"]')
                  || document.getElementById('g-recaptcha-response');
            if (!ta) {
                // Crear el textarea si no existe
                ta = document.createElement('textarea');
                ta.id = 'g-recaptcha-response';
                ta.name = 'g-recaptcha-response';
                ta.style.display = 'none';
                var container = document.getElementById('CAPTCHAContainerUC') || document.forms[0];
                container.appendChild(ta);
            }
            ta.value = token;
            ta.innerHTML = token;

            // Intentar callback de reCAPTCHA
            try {
                if (typeof ___grecaptcha_cfg !== 'undefined' && ___grecaptcha_cfg.clients) {
                    for (var key in ___grecaptcha_cfg.clients) {
                        var c = ___grecaptcha_cfg.clients[key];
                        // Recorrer propiedades buscando el callback
                        function findCallback(obj, depth) {
                            if (depth > 5 || !obj) return;
                            for (var k in obj) {
                                if (k === 'callback' && typeof obj[k] === 'function') {
                                    obj[k](token);
                                    return;
                                }
                                if (typeof obj[k] === 'object') findCallback(obj[k], depth + 1);
                            }
                        }
                        findCallback(c, 0);
                    }
                }
            } catch(e) {}
        """, token)
        print(f"[{timestamp()}] Token inyectado en la pagina")
        time.sleep(1)
        return True
    except Exception as e:
        print(f"[{timestamp()}] ERROR inyectando token: {e}")
        guardar_debug(driver, "captcha_inject_error")
        return False


# ============================================================
# EXTRACCION DE DATOS
# ============================================================
def extraer_persona(driver: uc.Chrome) -> Persona:
    """Extrae informacion de la persona y sus cuentas"""
    print(f"[{timestamp()}] Extrayendo datos de la persona...")

    # Guardar HTML post-login para debug
    guardar_debug(driver, "post_login")

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
    """Extrae las cuentas de la tabla GeneXus de la pagina post-login"""
    cuentas = []

    try:
        # Buscar filas de la grid GeneXus por su ID (GridwwContainerRow_XXXX)
        filas = driver.find_elements(By.CSS_SELECTOR, 'tr[id^="GridwwContainerRow_"]')

        for fila in filas:
            row_id = fila.get_attribute('data-gxrow') or ''  # "0001", "0002", etc.

            # Extraer datos usando los span IDs de GeneXus
            try:
                nro_text = driver.find_element(By.ID, f'span_vCUENTANRO_{row_id}').text.strip()
                nro = int(nro_text) if nro_text.isdigit() else 0
            except:
                nro = 0

            try:
                servicio = driver.find_element(By.ID, f'span_vCUENTASRV_{row_id}').text.strip()
            except:
                servicio = ''

            try:
                domicilio = driver.find_element(By.ID, f'span_vCUENTADOM_{row_id}').text.strip()
            except:
                domicilio = ''

            try:
                estado = driver.find_element(By.ID, f'span_vSTSDSC_{row_id}').text.strip()
            except:
                estado = ''

            cuenta = Cuenta(nro=nro, servicio=servicio, domicilio=domicilio, estado=estado)
            cuentas.append(cuenta)

        if not cuentas:
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
        row_id = f"{indice + 1:04d}"  # "0001", "0002", etc.
        img_id = f"vVERCUENTA_{row_id}"

        print(f"[{timestamp()}] Entrando al detalle de cuenta {cuenta.nro} ({cuenta.domicilio})...")

        # Click en el icono de detalle usando JavaScript (evita error de JS world)
        try:
            driver.execute_script(
                f"document.getElementById('{img_id}').click();"
            )
        except Exception:
            # Fallback: buscar por selector
            img = driver.find_element(By.ID, img_id)
            driver.execute_script("arguments[0].click();", img)

        time.sleep(5)

        # Verificar que la pagina cambio
        current_url = driver.current_url
        if 'cuentasselecion' in current_url.lower():
            # La pagina no cambio, intentar con evento GeneXus
            driver.execute_script(
                f"gx.evt.execEvt('',false,\"E'VER_CUENTA'.{row_id}\",document.getElementById('{img_id}'));"
            )
            time.sleep(5)

        # Extraer todo el contenido de la pagina de detalle
        detalle = parsear_pagina_detalle(driver)

        # Guardar debug de la pagina de detalle
        guardar_debug(driver, f"detalle_cuenta_{cuenta.nro}")

        # Volver a la lista de cuentas
        volver_a_cuentas(driver)

    except Exception as e:
        print(f"[{timestamp()}] ERROR extrayendo detalle cuenta {cuenta.nro}: {e}")
        guardar_debug(driver, f"error_detalle_cuenta_{cuenta.nro}")

    return detalle


def parsear_pagina_detalle(driver: uc.Chrome) -> Dict:
    """Parsea la pagina de detalle de una cuenta usando IDs GeneXus"""
    detalle = {}

    try:
        time.sleep(2)

        # Encabezado: Asociado, Domicilio, Detalle deuda
        for campo_id, campo_nombre in [
            ('LBLTEXTOENCABEZADO1', 'asociado'),
            ('LBLTEXTOENCABEZADO2', 'domicilio'),
            ('LBLTEXTOENCABEZADO3', 'periodo_deuda'),
        ]:
            try:
                elem = driver.find_element(By.ID, campo_id)
                texto = elem.text.strip()
                if texto:
                    # Limpiar prefijos como "Asociado: ", "Domicilio: "
                    if ':' in texto and campo_nombre != 'periodo_deuda':
                        texto = texto.split(':', 1)[-1].strip()
                    detalle[campo_nombre] = texto
            except NoSuchElementException:
                pass

        # Resumen pie: comprobantes adeudados e importe
        try:
            pie = driver.find_element(By.ID, 'LBLTEXTOPIE1').text.strip()
            if pie:
                detalle['resumen'] = pie
                # Extraer importe adeudado
                match_importe = re.search(r'Importe\s*Adeudado:\s*\$?([\d.,]+)', pie)
                if match_importe:
                    detalle['importe_adeudado'] = match_importe.group(1)
                # Extraer cantidad
                match_cant = re.search(r'Cant\.\s*comprobantes\s*adeudados:\s*(\d+)', pie)
                if match_cant:
                    detalle['comprobantes_adeudados'] = int(match_cant.group(1))
        except NoSuchElementException:
            pass

        # Verificar si dice SIN COMPROBANTES PENDIENTES
        body_text = driver.find_element(By.TAG_NAME, 'body').text
        if 'SIN COMPROBANTES PENDIENTES' in body_text:
            detalle['estado_deuda'] = 'SIN COMPROBANTES PENDIENTES'

        # Tabla de comprobantes (GridwwContainerTbl)
        comprobantes = []
        filas = driver.find_elements(By.CSS_SELECTOR, 'tr[id^="GridwwContainerRow_"]')
        for fila in filas:
            row_id = fila.get_attribute('data-gxrow') or ''
            comprobante = {}

            campos_comprobante = [
                (f'span_vCOLUMNA2_{row_id}', 'fecha_emision'),
                (f'span_vCOLUMNA5_{row_id}', 'fecha_vencimiento'),
                (f'span_vCOLUMNA3_{row_id}', 'comprobante'),
                (f'span_vIMPORTEC_{row_id}', 'importe'),
                (f'span_vCOLUMNA10_{row_id}', 'estado'),
            ]

            for span_id, nombre in campos_comprobante:
                try:
                    val = driver.find_element(By.ID, span_id).text.strip()
                    if val:
                        comprobante[nombre] = val
                except NoSuchElementException:
                    pass

            if comprobante:
                comprobantes.append(comprobante)

        if comprobantes:
            detalle['comprobantes'] = comprobantes

    except Exception as e:
        detalle['error'] = str(e)

    return detalle


def volver_a_cuentas(driver: uc.Chrome):
    """Vuelve a la pagina de cuentas usando el boton BTNBACK"""
    try:
        # Usar boton Volver de GeneXus
        try:
            driver.execute_script("document.getElementById('BTNBACK').click();")
        except Exception:
            btn = driver.find_element(By.ID, 'BTNBACK')
            btn.click()
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
            d = c.detalle
            print(f"\n{'-' * 70}")
            print(f"  DETALLE CUENTA {c.nro} - {c.domicilio}")
            print(f"{'-' * 70}")

            if d.get('asociado'):
                print(f"  Asociado: {d['asociado']}")
            if d.get('domicilio'):
                print(f"  Domicilio: {d['domicilio']}")
            if d.get('periodo_deuda'):
                print(f"  {d['periodo_deuda']}")

            if d.get('estado_deuda'):
                print(f"\n  [OK] {d['estado_deuda']}")
            elif d.get('comprobantes_adeudados'):
                print(f"\n  [!] Comprobantes adeudados: {d['comprobantes_adeudados']}")
                if d.get('importe_adeudado'):
                    print(f"  [!] Importe adeudado: ${d['importe_adeudado']}")

            if d.get('comprobantes'):
                print(f"\n  {'Fecha Emis.':<12} {'Fecha Vto.':<12} {'Comprobante':<25} {'Importe':>12} {'Estado':<10}")
                print(f"  {'-' * 73}")
                for comp in d['comprobantes']:
                    print(f"  {comp.get('fecha_emision', ''):.<12} "
                          f"{comp.get('fecha_vencimiento', ''):<12} "
                          f"{comp.get('comprobante', ''):<25} "
                          f"{comp.get('importe', ''):>12} "
                          f"{comp.get('estado', ''):<10}")

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
                d = c.detalle
                w.writerow([f'DETALLE CUENTA {c.nro} - {c.domicilio}'])
                if d.get('asociado'):
                    w.writerow(['Asociado', d['asociado']])
                if d.get('domicilio'):
                    w.writerow(['Domicilio', d['domicilio']])
                if d.get('periodo_deuda'):
                    w.writerow(['Periodo', d['periodo_deuda']])
                if d.get('estado_deuda'):
                    w.writerow(['Estado Deuda', d['estado_deuda']])
                if d.get('comprobantes_adeudados') is not None:
                    w.writerow(['Comprobantes Adeudados', d['comprobantes_adeudados']])
                if d.get('importe_adeudado'):
                    w.writerow(['Importe Adeudado', d['importe_adeudado']])
                w.writerow([])

                if d.get('comprobantes'):
                    w.writerow(['Fecha Emision', 'Fecha Vencimiento', 'Comprobante', 'Importe', 'Estado'])
                    for comp in d['comprobantes']:
                        w.writerow([
                            comp.get('fecha_emision', ''),
                            comp.get('fecha_vencimiento', ''),
                            comp.get('comprobante', ''),
                            comp.get('importe', ''),
                            comp.get('estado', ''),
                        ])
                w.writerow([])

    print(f"[{timestamp()}] CSV exportado: {ruta.resolve()}")


# ============================================================
# MAIN
# ============================================================
def main():
    headless = '--no-headless' not in sys.argv
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
