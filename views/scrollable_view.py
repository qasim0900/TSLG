"""Vista base con scroll automático reutilizable por todas las pantallas."""
import flet as ft


class ScrollableView(ft.Column):
    """
    Vista reutilizable con scroll automático.
    Facilita la reutilización del patrón scroll entre diferentes vistas.
    """
    
    def __init__(self, expand=True, spacing=20):
        # Crear una columna interna que contendrá el contenido
        self._content_column = ft.Column(
            spacing=spacing,
            expand=True
        )
        
        # Envolver en scroll
        super().__init__(
            expand=expand,
            spacing=0,
            controls=[
                ft.Column(
                    [self._content_column],
                    spacing=0,
                    expand=True,
                    scroll=ft.ScrollMode.AUTO,
                )
            ]
        )
    
    def add_control(self, control):
        """Agrega un control a la columna scrolleable."""
        self._content_column.controls.append(control)
    
    def clear_controls(self):
        """Limpia todos los controles de la columna scrolleable."""
        self._content_column.controls.clear()
    
    def set_controls(self, controls):
        """Establece una lista de controles en la columna scrolleable."""
        self._content_column.controls = controls
    
    def get_content_column(self):
        """Retorna la columna interna para acceso directo."""
        return self._content_column
