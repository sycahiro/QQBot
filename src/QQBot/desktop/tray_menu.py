"""Small themed native tray popup, owned by the existing tray UI thread."""


def dark_theme(preference):
    if preference != "system":
        return preference == "dark"
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


class TrayMenu:
    def __init__(self, show, exit_app, theme):
        from System.Drawing import Color, ContentAlignment, Font, Point, Size
        from System.Windows.Forms import (
            Button,
            FlatStyle,
            Form,
            FormBorderStyle,
            FormStartPosition,
        )

        self._color, self._point, self._theme = Color, Point, theme
        self._form = Form()
        form = self._form
        form.Text = "QQBot"
        form.FormBorderStyle = getattr(FormBorderStyle, "None")
        form.StartPosition = FormStartPosition.Manual
        form.ShowInTaskbar = False
        form.TopMost = True
        form.ClientSize = Size(236, 110)
        self._font = Font("Microsoft YaHei UI", 10)
        form.Font = self._font
        self._buttons = []
        for index, (label, callback) in enumerate([("打开工作台", show), ("退出 QQBot", exit_app)]):
            button = Button()
            button.Text = label
            button.FlatStyle = FlatStyle.Flat
            button.FlatAppearance.BorderSize = 0
            button.TextAlign = ContentAlignment.MiddleLeft
            button.Location = Point(10, 10 + index * 48)
            button.Size = Size(216, 42)

            def clicked(_, event, callback=callback):
                form.Hide()
                callback()

            button.Click += clicked
            form.Controls.Add(button)
            self._buttons.append(button)
        form.Deactivate += lambda *_: form.Hide()
        form.KeyPreview = True
        form.KeyDown += lambda _, event: form.Hide() if str(event.KeyCode) == "Escape" else None
        # Rounded corners without a custom renderer or additional UI runtime.
        from System.Drawing import Region
        from System.Drawing.Drawing2D import GraphicsPath

        path = GraphicsPath()
        for x, y, start in [(0, 0, 180), (220, 0, 270), (220, 94, 0), (0, 94, 90)]:
            path.AddArc(x, y, 16, 16, start, 90)
        path.CloseFigure()
        form.Region = Region(path)
        path.Dispose()

    def _apply_theme(self):
        color = self._color.FromArgb
        dark = dark_theme(self._theme())
        background = color(20, 30, 41) if dark else color(255, 255, 255)
        foreground = color(230, 237, 244) if dark else color(13, 25, 36)
        hover = color(32, 50, 65) if dark else color(234, 245, 250)
        self._form.BackColor = background
        for button in self._buttons:
            button.BackColor = background
            button.ForeColor = foreground
            button.FlatAppearance.MouseOverBackColor = hover
            button.FlatAppearance.MouseDownBackColor = hover

    def show(self):
        from System.Windows.Forms import Cursor, Screen

        self._apply_theme()
        cursor = Cursor.Position
        area = Screen.FromPoint(cursor).WorkingArea
        self._form.Location = self._point(
            max(area.Left, min(cursor.X, area.Right - self._form.Width)),
            max(area.Top, min(cursor.Y - self._form.Height, area.Bottom - self._form.Height)),
        )
        self._form.Show()
        self._form.Activate()
        self._buttons[0].Focus()

    def close(self):
        self._form.Dispose()
        self._font.Dispose()
