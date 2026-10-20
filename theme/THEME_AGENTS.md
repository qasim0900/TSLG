# THEME_AGENTS.md — Contrato Técnico del Sistema de Theme

**Versión:** 1.1.0  
**Fecha:** 2026-03-04  
**Estado:** Vigente — Patrón Oficial Flet 0.82.0 + Single Render Owner Pattern  
**Audiencia:** Developers, AI Agents  
**Autoridad:** Este documento es la ÚNICA fuente de verdad para modificaciones en `/theme/`

---

## 📌 PRÓLOGO

Este documento define el contrato técnico del sistema de theme en TSS_FDT_Sales_Manager.

**Regla fundamental:**  
Cualquier modificación en `/theme/` debe adherirse ESTRICTAMENTE a este documento.

---

## 1. PATRÓN OFICIAL FLET 0.81.0

### 1.1 Configuración del Theme (main.py)

```python
# ✅ CORRECTO: Configurar UNA vez al inicio
page.theme = build_light_theme()
page.dark_theme = build_dark_theme()
page.theme_mode = ft.ThemeMode.LIGHT
```

**Responsabilidades:**
- ✅ `build_light_theme()` y `build_dark_theme()` se configuran UNA sola vez
- ✅ `page.theme_mode` es el ÚNICO valor que cambia durante ejecución
- ❌ NUNCA reasignar `page.theme` o `page.dark_theme` después del inicio

### 1.2 Toggle de Theme (ui/user_ui.py) — Single Render Owner Pattern

```python
# ✅ CORRECTO: Toggle simple con actualización de vista activa
def _toggle_theme(self, e):
    # 1. Cambiar theme_mode (Flet auto-actualiza colores semánticos)
    self.page.theme_mode = (
        ft.ThemeMode.LIGHT 
        if self.page.theme_mode == ft.ThemeMode.DARK 
        else ft.ThemeMode.DARK
    )
    
    # 2. Actualizar vista activa (si implementa update_theme)
    active_view = self.body.content
    if active_view and hasattr(active_view, 'update_theme'):
        active_view.update_theme()
    
    # 3. UNA sola llamada a page.update() (Multi-Render Owner anti-pattern)
    self.page.update()
```

**Prohibiciones:**
- ❌ NO llamar wrapper `update_theme(page, preset)` (removido)
- ❌ NO llamar `page.update()` múltiples veces
- ❌ NO reconstruir componentes en toggle
- ❌ NO hacer page.update() en cada vista durante theme change (centralizar en router)

---

## 2. JERARQUÍA DE COLORES

### 2.1 Colores Semánticos (PREFERIDOS)

**Usar SIEMPRE que sea posible:**

| Propósito | Color Semántico | Auto-actualiza |
|-----------|----------------|----------------|
| Texto principal | `ft.Colors.ON_SURFACE` | ✅ |
| Texto secundario | `ft.Colors.ON_SURFACE_VARIANT` | ✅ |
| Fondos de tarjetas | `ft.Colors.SURFACE` | ✅ |
| Fondos elevados | `ft.Colors.SURFACE_CONTAINER` | ✅ |
| Fondos más elevados | `ft.Colors.SURFACE_CONTAINER_HIGHEST` | ✅ |
| Color primario | `ft.Colors.PRIMARY` | ✅ |
| Texto sobre primario | `ft.Colors.ON_PRIMARY` | ✅ |
| Bordes | `ft.Colors.OUTLINE` | ✅ |

**Ventaja:** Flet los actualiza automáticamente al cambiar `theme_mode`.

### 2.2 Colores Condicionales (EXCEPCIONES)

**Usar SOLO cuando hay razón funcional (no estética):**

```python
# ✅ PERMITIDO: Semántica funcional (inicio/fin de período)
if is_start:
    bgcolor = ft.Colors.GREEN_700 if is_dark else ft.Colors.GREEN_200
else:
    bgcolor = ft.Colors.RED_700 if is_dark else ft.Colors.RED_200

# ✅ PERMITIDO: Diferenciación de paneles (FilterPanel vs ComparePanel)
def get_filter_panel_bgcolor(theme_mode):
    return ft.Colors.with_opacity(0.15, ft.Colors.BLUE_300) if is_dark else ft.Colors.with_opacity(0.1, ft.Colors.BLUE_600)

def get_compare_panel_bgcolor(theme_mode):
    return ft.Colors.with_opacity(0.18, ft.Colors.AMBER_300) if is_dark else ft.Colors.with_opacity(0.12, ft.Colors.AMBER_600)

# ✅ PERMITIDO: Contraste de gráficos
def get_chart_palette(theme_mode):
    if is_dark:
        return [ft.Colors.CYAN, ft.Colors.AMBER, ft.Colors.LIME, ...]
    else:
        return [ft.Colors.BLUE, ft.Colors.RED, ft.Colors.GREEN, ...]
```

**Razones válidas para condicionales:**
- Semántica funcional (verde=positivo, rojo=negativo)
- Diferenciación entre paneles (BLUE vs AMBER)
- Contraste específico en gráficos
- Identidad visual de marca

**Razones NO válidas:**
- "Se ve mejor así"
- "Es tradición del código"
- "Simplemente prefiero este color"

### 2.3 Colores Hardcodeados (PROHIBIDO)

```python
# ❌ PROHIBIDO
text_color = ft.Colors.WHITE if is_dark else ft.Colors.BLACK

# ✅ CORRECTO
text_color = ft.Colors.ON_SURFACE
```

---

## 3. ESTRUCTURA DE `/theme/`

### 3.1 Archivos y Responsabilidades

| Archivo | Propósito | Puede tener condicionales |
|---------|-----------|---------------------------|
| `builders.py` | Construir `ft.Theme` para light/dark | NO |
| `colors.py` | Constantes de marca + funciones de botones | SÍ (botones) |
| `theme_utils.py` | Helpers de colores | SOLO excepciones |
| `kpi_styles.py` | Estilos de KPI cards | SOLO ajustes visuales |
| `components.py` | Widgets reutilizables | SOLO excepciones |

### 3.2 Contenido Obligatorio

#### `builders.py`

```python
def build_light_theme() -> ft.Theme:
    """Construye tema claro. Se configura UNA vez en main.py."""
    return ft.Theme(
        color_scheme_seed=PRIMARY_COLOR,
        use_material3=True,
    )

def build_dark_theme() -> ft.Theme:
    """Construye tema oscuro. Se configura UNA vez en main.py."""
    return ft.Theme(
        color_scheme_seed=PRIMARY_DARK,
        use_material3=True,
    )
```

**Prohibiciones:**
- ❌ NO incluir función `update_theme(page, preset)` (removida)
- ❌ NO llamar `page.update()` dentro de builders
- ❌ NO modificar `page.theme_mode`

#### `theme_utils.py`

**Helpers básicos (wrapper de colores semánticos):**

```python
def get_text_color(page_or_theme_mode) -> str:
    """Wrapper: Devuelve ft.Colors.ON_SURFACE."""
    return ft.Colors.ON_SURFACE

def get_subtitle_color(page_or_theme_mode) -> str:
    """Wrapper: Devuelve ft.Colors.ON_SURFACE_VARIANT."""
    return ft.Colors.ON_SURFACE_VARIANT

def get_card_color(page_or_theme_mode) -> str:
    """Wrapper: Devuelve ft.Colors.SURFACE."""
    return ft.Colors.SURFACE

def get_icon_color(page_or_theme_mode) -> str:
    """Wrapper: Devuelve ft.Colors.PRIMARY."""
    return ft.Colors.PRIMARY

def get_container_translucent_bgcolor(page_or_theme_mode) -> str:
    """Fondo translúcido con opacidad adaptativa (excepción justificada)."""
    if is_dark_mode(page_or_theme_mode):
        return ft.Colors.with_opacity(0.15, ft.Colors.ON_SURFACE)
    else:
        return ft.Colors.with_opacity(0.08, ft.Colors.PRIMARY)
```

**Estado:** ✅ VÁLIDOS PARA USO  
**Razón:** Proporcionan abstracción semántica. El parámetro `page_or_theme_mode` se mantiene por compatibilidad pero no afecta el resultado (excepto en `get_container_translucent_bgcolor` que usa opacidades diferentes).

**Helpers especializados (condicionales justificados):**

```python
def get_filter_panel_bgcolor(page_or_theme_mode) -> str:
    """PERMITIDO: Diferenciación visual de panel."""
    if is_dark_mode(page_or_theme_mode):
        return ft.Colors.with_opacity(0.15, ft.Colors.BLUE_300)
    return ft.Colors.with_opacity(0.1, ft.Colors.BLUE_600)

def get_compare_panel_bgcolor(page_or_theme_mode) -> str:
    """PERMITIDO: Diferenciación visual de panel."""
    if is_dark_mode(page_or_theme_mode):
        return ft.Colors.with_opacity(0.18, ft.Colors.AMBER_300)
    else:
        return ft.Colors.with_opacity(0.12, ft.Colors.AMBER_600)

def get_chart_palette(page_or_theme_mode) -> list:
    """PERMITIDO: Contraste específico de gráficos."""
    if is_dark_mode(page_or_theme_mode):
        return [ft.Colors.CYAN, ft.Colors.AMBER, ...]
    else:
        return [ft.Colors.BLUE, ft.Colors.RED, ...]

def get_compare_delta_color(page_or_theme_mode, delta: float) -> str:
    """PERMITIDO: Semántica universal (verde=positivo, rojo=negativo)."""
    if delta > 0:
        return ft.Colors.GREEN_300 if is_dark else ft.Colors.GREEN_700
    elif delta < 0:
        return ft.Colors.RED_300 if is_dark else ft.Colors.RED_700
    return ft.Colors.GREY_400 if is_dark else ft.Colors.GREY_700

def get_dashboard_card_colors(page_or_theme_mode) -> dict:
    """Devuelve diccionario de colores semánticos (sin condicionales)."""
    return {
        "bg_card": ft.Colors.SURFACE_CONTAINER,
        "icon": ft.Colors.PRIMARY,
        "text": ft.Colors.ON_SURFACE,
        "subtitle": ft.Colors.ON_SURFACE_VARIANT,
    }
```

**Estado:** ✅ VÁLIDOS - Excepciones justificadas según §2.2

**Utilidades recursivas (Legacy):**

```python
def update_container_theme(container, theme_mode, set_bg=True):
    """Actualiza tema de container y contenido recursivamente."""
    # Usado en componentes legacy que no implementan update_theme()
    
def update_component_theme_recursive(component, theme_mode):
    """Actualiza tema de componente y sub-componentes."""
    # Usado en componentes complejos
```

**Estado:** ⚠️ LEGACY - Mantener por compatibilidad. Preferir Patrón B (update_theme individual)
        return ft.Colors.with_opacity(0.18, ft.Colors.AMBER_300)
    else:
        return ft.Colors.with_opacity(0.12, ft.Colors.AMBER_600)

def get_chart_palette(page_or_theme_mode) -> list:
    """PERMITIDO: Contraste específico de gráficos."""
    if is_dark_mode(page_or_theme_mode):
        return [ft.Colors.CYAN, ft.Colors.AMBER, ...]
    else:
        return [ft.Colors.BLUE, ft.Colors.RED, ...]
```

#### `colors.py`

**Constantes de marca:**

```python
PRIMARY_COLOR = ft.Colors.BLUE_600
PRIMARY_DARK = ft.Colors.BLUE_300

# DEPRECATED
TEXT_LIGHT = ft.Colors.BLACK
TEXT_DARK = ft.Colors.WHITE
CARD_LIGHT = ft.Colors.WHITE
CARD_DARK = ft.Colors.GREY_800
```

**Funciones de botones:**

```python
def get_apply_filter_colors(is_dark_mode: bool):
    return {
        'bgcolor': ft.Colors.BLUE_600 if is_dark_mode else ft.Colors.BLUE_700,
        'hover_bgcolor': ft.Colors.BLUE_800,
        'color': ft.Colors.ON_PRIMARY,  # ✅ Semántico
        'elevation': 5,
    }
```

---

## 4. PATRONES DE COMPONENTES

### 4.1 Patrón A: Sin `update_theme()`

**Para componentes que SOLO usan colores semánticos:**

```python
class SimpleCard(ft.Container):
    def __init__(self):
        super().__init__(
            bgcolor=ft.Colors.SURFACE,  # ✅ Semántico
            content=ft.Text(
                "Texto",
                color=ft.Colors.ON_SURFACE,  # ✅ Semántico
            ),
        )
```

**Sin método `update_theme()`** — Flet actualiza automáticamente.

### 4.2 Patrón B: Con `update_theme()` (mutación)

**Para componentes que usan condicionales o cachean referencias:**

```python
class ComplexCard(ft.Container):
    def __init__(self):
        self._title_text = None
        self._card_bg = None
        super().__init__()
    
    def build(self):
        self._title_text = ft.Text("Título")
        self._card_bg = ft.Container()
        # construir UI
    
    def update_theme(self):
        """Actualiza SOLO colores, NO reconstruye."""
        if not self.page:
            return
        
        theme_mode = self.page.theme_mode
        
        # Mutar propiedades
        self._title_text.color = ft.Colors.ON_SURFACE
        self._card_bg.bgcolor = get_filter_panel_bgcolor(theme_mode)
        
        # NO llamar self.update() aquí
```

**Reglas del Patrón B:**
- ✅ SOLO mutar propiedades visuales
- ✅ Cachear referencias en `__init__` o `build()`
- ❌ NO reconstruir componentes
- ❌ NO llamar `self.update()` o `page.update()`

### 4.3 Patrón C: Reconstrucción (SOLO si cambian datos)

```python
def update_from_snapshot(self, new_snapshot):
    """Reconstruir SOLO cuando cambian los datos."""
    self._snapshot = new_snapshot
    self.content = self._build_chart()  # Reconstrucción permitida
    # La vista llama page.update()
```

---

## 5. VALIDACIÓN DE CUMPLIMIENTO

### 5.1 Checklist para Nuevos Componentes

- [ ] ¿Usa colores semánticos directos O helpers wrapper cuando sea posible?
- [ ] ¿Los condicionales tienen razón funcional documentada?
- [ ] ¿Implementa `update_theme()` solo si es necesario?
- [ ] ¿`update_theme()` solo muta, no reconstruye?
- [ ] ¿NO llama `page.update()` internamente?
- [ ] ¿NO usa condicionales manuales para colores básicos (text, subtitle, card)?

### 5.2 Helpers: ¿Cuándo usar qué?

**Preferencia en código nuevo:**

| Situación | Usar | Ejemplo |
|-----------|------|---------|
| Texto principal | `ft.Colors.ON_SURFACE` | `color=ft.Colors.ON_SURFACE` |
| Texto secundario | `ft.Colors.ON_SURFACE_VARIANT` | `color=ft.Colors.ON_SURFACE_VARIANT` |
| Fondo de tarjeta | `ft.Colors.SURFACE` | `bgcolor=ft.Colors.SURFACE` |
| Iconos | `ft.Colors.PRIMARY` | `color=ft.Colors.PRIMARY` |
| **Abstracción semántica** | Helpers wrapper | `color=get_text_color(theme_mode)` |
| Fondos translúcidos | `get_container_translucent_bgcolor()` | **OBLIGATORIO** (opacidad adaptativa) |
| Paneles diferenciados | `get_filter_panel_bgcolor()` | **OBLIGATORIO** (BLUE vs AMBER) |
| Paletas de gráficos | `get_chart_palette()` | **OBLIGATORIO** (contraste específico) |
| Deltas de comparación | `get_compare_delta_color()` | **OBLIGATORIO** (semántica universal) |

**Regla general:**
- ✅ **Colores directos** son más claros y explícitos
- ✅ **Helpers wrapper** son válidos para abstracción semántica
- ✅ **Helpers especializados** son obligatorios cuando tienen lógica condicional justificada

**Ambos enfoques son correctos y válidos.**

### 5.3 Red Flags (Señales de Alerta)

❌ **Prohibido absolutamente:**
- Llamar `page.update()` múltiples veces en un toggle
- Recrear componentes en `update_theme()`
- Usar `ft.Colors.WHITE`/`BLACK` en lugar de `ON_SURFACE`/`ON_PRIMARY`
- Wrapper `update_theme(page, preset)` (removido)
- Modificar `page.theme` o `page.dark_theme` después del inicio

⚠️ **Requiere justificación:**
- Lógica `if is_dark_mode()` en helper
- Color específico no semántico
- Nuevo helper condicional

---

## 6. FLUJO DE ACTUALIZACIÓN

### 6.1 Flujo Normal (Usuario Cambia Theme)

```
1. Usuario presiona botón toggle
       ↓
2. ui/user_ui.py:_toggle_theme()
   - Cambia page.theme_mode
       ↓
3. Llama active_view.update_theme()
   - Vista muta colores de sus componentes
   - Vista llama update_theme() de componentes hijos
       ↓
4. UNA llamada a page.update()
       ↓
5. Flet actualiza AUTOMÁTICAMENTE:
   - Todos los ft.Colors.ON_SURFACE
   - Todos los ft.Colors.SURFACE
   - Todos los ft.Colors.PRIMARY
   - Etc.
```

### 6.2 Responsabilidades por Capa

| Capa | Responsabilidad Theme |
|------|----------------------|
| main.py | Configurar themes UNA vez |
| ui/user_ui.py | Toggle `theme_mode` + llamar vista activa |
| views/ | Orquestar `update_theme()` de componentes |
| components/ | Mutar colores propios (Patrón B) |
| theme/ | Proveer helpers y builders |

---

## 7. EXCEPCIONES DOCUMENTADAS

### 7.1 Colores de Gráficos

**Razón:** Contraste específico necesario para legibilidad.

```python
def get_chart_palette(page_or_theme_mode) -> list:
    if is_dark_mode(page_or_theme_mode):
        return [ft.Colors.CYAN, ft.Colors.AMBER, ft.Colors.LIME, ...]
    else:
        return [ft.Colors.BLUE, ft.Colors.RED, ft.Colors.GREEN, ...]
```

### 7.2 Paneles Diferenciados

**Razón:** Identidad visual de FilterPanel (BLUE) vs ComparePanel (AMBER).

```python
# FilterPanel: BLUE
get_filter_panel_bgcolor()  # Returns BLUE_300 / BLUE_600

# ComparePanel: AMBER
get_compare_panel_bgcolor()  # Returns AMBER_300 / AMBER_600
```

### 7.3 Chips de Fecha

**Razón:** Semántica funcional (inicio=verde, fin=rojo).

```python
def date_picker_chip(is_start: bool, ...):
    if is_start:
        bgcolor = ft.Colors.GREEN_700 if is_dark else ft.Colors.GREEN_200
    else:
        bgcolor = ft.Colors.RED_700 if is_dark else ft.Colors.RED_200
```

### 7.4 Deltas de Comparación

**Razón:** Semántica universal (positivo=verde, negativo=rojo).

```python
def get_compare_delta_color(delta: float):
    if delta > 0:
        return ft.Colors.GREEN_300 if is_dark else ft.Colors.GREEN_700
    elif delta < 0:
        return ft.Colors.RED_300 if is_dark else ft.Colors.RED_700
```

---

## 8. MIGRACIÓN DESDE PATRÓN ANTIGUO

### 8.1 Antes (INCORRECTO)

```python
# ❌ ANTIGUO: Wrapper + doble update
from theme import update_theme

def toggle():
    preset = "dark" if current == "light" else "light"
    update_theme(page, preset)  # Llama page.update()
    view.update_theme()
    page.update()  # ❌ Segunda llamada
```

### 8.2 Después (CORRECTO)

```python
# ✅ NUEVO: Directo + single update
def toggle():
    page.theme_mode = (
        ft.ThemeMode.DARK 
        if page.theme_mode == ft.ThemeMode.LIGHT 
        else ft.ThemeMode.LIGHT
    )
    view.update_theme()
    page.update()  # ✅ Una sola llamada
```

---

## 9. CHANGELOG

### v1.1.0 (2026-03-04) — Upgrade Flet 0.81.0 + Single Render Owner Pattern

**Cambios principales:**
- 🔧 **Flet 0.80.5+ → 0.81.0** — Actualización de versión de referencia
- ✨ **Single Render Owner Pattern integrado** — Documentación del flujo en § 1.2
- 📝 **Clarificaciones en rules de prohibición** — Agregadas pautas anti-pattern
- ✅ **Validación:** THEME_AGENTS.md es compatible con Flet 0.81.0

**Compatibility:**
- ✅ 100% backward compatible con Flet 0.80.5
- ✅ No hay breaking changes en patrones de theme
- ✅ Colores semánticos auto-actualización sin cambios

**Estado:** 🟢 **VIGENTE**

---

### v1.0.0 (2026-02-04) — Contrato Inicial

**Creación del documento:**
- Patrón oficial Flet 0.81.0 documentado
- Jerarquía de colores (semánticos > condicionales > hardcoded)
- Patrones A, B, C para componentes
- Excepciones justificadas documentadas
- Checklist de validación
- Flujo de actualización definido

**Motivación:**
Unificar criterios para que AI agents y developers apliquen consistentemente el sistema de theme sin ambigüedades ni regresiones.

---

**FIN DE THEME_AGENTS.md v1.0.0**
