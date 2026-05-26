"""
Todo App — 全功能离线 Todo 应用
================================
基于 Kivy + KivyMD 框架，SQLite 本地存储，Material Design 风格。

安装依赖:
    pip install kivy kivymd

Android 打包 (Buildozer):
    pip install buildozer
    buildozer init
    buildozer android debug deploy run

三个主 Tab:
  1. Todo 双区看板 (急需 / 普通)
  2. 项目工作流时间线
  3. 日历日程视图
"""

import sqlite3
import json
import os
from datetime import date, datetime, timedelta
from calendar import monthrange

from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.widget import Widget
from kivy.metrics import dp, sp
from kivy.clock import Clock
from kivy.graphics import Color, RoundedRectangle, Line, Ellipse
from kivy.utils import get_color_from_hex, platform
from kivy.core.window import Window
from kivy.properties import (
    ObjectProperty, StringProperty, ListProperty,
    NumericProperty, BooleanProperty,
)

# ── KivyMD imports ─────────────────────────────────────────────
from kivymd.app import MDApp
from kivymd.uix.card import MDCard
from kivymd.uix.dialog import (
    MDDialog, MDDialogHeadlineText, MDDialogContentContainer,
    MDDialogButtonContainer,
)
from kivymd.uix.button import (
    MDRaisedButton, MDFlatButton, MDIconButton,
    MDButton, MDButtonText,
)
from kivymd.uix.textfield import MDTextField, MDTextFieldHintText
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.gridlayout import MDGridLayout
from kivymd.uix.screen import MDScreen
from kivymd.uix.scrollview import MDScrollView
from kivymd.uix.selectioncontrol import MDCheckbox
from kivymd.uix.pickers import MDDatePicker
from kivymd.uix.snackbar import MDSnackbar, MDSnackbarText
from kivymd.uix.label import MDLabel
from kivymd.uix.divider import MDDivider
from kivymd.uix.chip import MDChip, MDChipText

# ── Color palette ──────────────────────────────────────────────
PRIORITY_COLORS = {
    "urgent": get_color_from_hex("#E53935"),
    "low":     get_color_from_hex("#757575"),
}
BG_LIGHT         = get_color_from_hex("#F5F5F5")
CARD_BG          = get_color_from_hex("#FFFFFF")
ACCENT           = get_color_from_hex("#1565C0")
ACCENT_LIGHT     = get_color_from_hex("#42A5F5")
TEXT_PRIMARY     = get_color_from_hex("#212121")
TEXT_SECONDARY   = get_color_from_hex("#757575")
DIVIDER_COLOR    = get_color_from_hex("#BDBDBD")
GREEN_DONE       = get_color_from_hex("#4CAF50")

IS_ANDROID = platform == "android"
IS_MOBILE  = IS_ANDROID or platform == "ios"
Window.softinput_mode = "below_target"


# ╔══════════════════════════════════════════════════════════════╗
# ║                      DATABASE  LAYER                        ║
# ╚══════════════════════════════════════════════════════════════╝

class DB:
    """SQLite database with all CRUD operations."""

    _path = None

    @classmethod
    def init(cls, user_data_dir: str):
        cls._path = os.path.join(user_data_dir, "todo.db")
        cls._create_tables()

    @classmethod
    def _conn(cls):
        conn = sqlite3.connect(cls._path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @classmethod
    def _create_tables(cls):
        with cls._conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    title         TEXT    NOT NULL,
                    priority      TEXT    NOT NULL DEFAULT 'low',
                    due_date      TEXT,
                    is_completed  INTEGER NOT NULL DEFAULT 0,
                    project_id    INTEGER,
                    milestone_id  INTEGER,
                    created_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
                    FOREIGN KEY (project_id)   REFERENCES projects(id) ON DELETE SET NULL,
                    FOREIGN KEY (milestone_id) REFERENCES milestones(id) ON DELETE SET NULL
                );
                CREATE TABLE IF NOT EXISTS projects (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    title       TEXT    NOT NULL,
                    description TEXT    DEFAULT '',
                    start_date  TEXT,
                    end_date    TEXT
                );
                CREATE TABLE IF NOT EXISTS milestones (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id  INTEGER NOT NULL,
                    title       TEXT    NOT NULL,
                    date        TEXT    NOT NULL,
                    is_done     INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS notes (
                    id      INTEGER PRIMARY KEY AUTOINCREMENT,
                    date    TEXT    NOT NULL,
                    content TEXT    NOT NULL
                );
            """)

    # ── Tasks ──────────────────────────────────────────────────

    @classmethod
    def add_task(cls, title, priority="low", due_date=None,
                 project_id=None, milestone_id=None):
        with cls._conn() as c:
            c.execute(
                "INSERT INTO tasks (title, priority, due_date, project_id, milestone_id)"
                " VALUES (?, ?, ?, ?, ?)",
                (title, priority, due_date, project_id, milestone_id),
            )
            return c.lastrowid

    @classmethod
    def update_task(cls, task_id, **kwargs):
        allowed = {"title", "priority", "due_date", "is_completed",
                   "project_id", "milestone_id"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return
        cols = ", ".join(f"{k}=?" for k in updates)
        vals = list(updates.values()) + [task_id]
        with cls._conn() as c:
            c.execute(f"UPDATE tasks SET {cols} WHERE id=?", vals)

    @classmethod
    def delete_task(cls, task_id):
        with cls._conn() as c:
            c.execute("DELETE FROM tasks WHERE id=?", (task_id,))

    @classmethod
    def get_tasks_by_priority(cls, priority, include_completed=False):
        clause = "" if include_completed else "AND is_completed = 0"
        with cls._conn() as c:
            return [dict(r) for r in c.execute(
                f"SELECT * FROM tasks WHERE priority=? {clause} "
                f"ORDER BY COALESCE(due_date,'9999-99-99'), created_at",
                (priority,),
            ).fetchall()]

    @classmethod
    def get_completed_tasks(cls, limit=50):
        with cls._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM tasks WHERE is_completed=1 "
                "ORDER BY created_at DESC LIMIT ?", (limit,),
            ).fetchall()]

    @classmethod
    def get_tasks_by_date(cls, date_str):
        with cls._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM tasks WHERE due_date=? AND is_completed=0",
                (date_str,),
            ).fetchall()]

    @classmethod
    def get_tasks_by_milestone(cls, milestone_id):
        with cls._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM tasks WHERE milestone_id=? AND is_completed=0",
                (milestone_id,),
            ).fetchall()]

    @classmethod
    def get_tasks_by_project(cls, project_id):
        with cls._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM tasks WHERE project_id=? AND is_completed=0 "
                "ORDER BY COALESCE(due_date,'9999-99-99')",
                (project_id,),
            ).fetchall()]

    @classmethod
    def get_all_tasks_grouped_by_date(cls, year=None, month=None):
        """Return {date_str: [task_dict, ...]} for calendar dots."""
        where = "WHERE is_completed=0 AND due_date IS NOT NULL"
        params = []
        if year and month:
            prefix = f"{year:04d}-{month:02d}"
            where += " AND due_date LIKE ?"
            params.append(f"{prefix}%")
        with cls._conn() as c:
            rows = c.execute(
                f"SELECT * FROM tasks {where} ORDER BY due_date", params
            ).fetchall()
        result = {}
        for r in rows:
            d = dict(r)
            result.setdefault(d["due_date"], []).append(d)
        return result

    # ── Projects ───────────────────────────────────────────────

    @classmethod
    def add_project(cls, title, description="", start_date=None, end_date=None):
        with cls._conn() as c:
            c.execute(
                "INSERT INTO projects (title, description, start_date, end_date)"
                " VALUES (?,?,?,?)",
                (title, description, start_date, end_date),
            )
            return c.lastrowid

    @classmethod
    def update_project(cls, project_id, **kwargs):
        allowed = {"title", "description", "start_date", "end_date"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return
        cols = ", ".join(f"{k}=?" for k in updates)
        vals = list(updates.values()) + [project_id]
        with cls._conn() as c:
            c.execute(f"UPDATE projects SET {cols} WHERE id=?", vals)

    @classmethod
    def delete_project(cls, project_id):
        with cls._conn() as c:
            c.execute("DELETE FROM projects WHERE id=?", (project_id,))

    @classmethod
    def get_all_projects(cls):
        with cls._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM projects ORDER BY COALESCE(start_date,'9999-99-99')"
            ).fetchall()]

    @classmethod
    def get_project(cls, project_id):
        with cls._conn() as c:
            r = c.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
            return dict(r) if r else None

    # ── Milestones ─────────────────────────────────────────────

    @classmethod
    def add_milestone(cls, project_id, title, date_str):
        with cls._conn() as c:
            c.execute(
                "INSERT INTO milestones (project_id, title, date) VALUES (?,?,?)",
                (project_id, title, date_str),
            )
            return c.lastrowid

    @classmethod
    def update_milestone(cls, milestone_id, **kwargs):
        allowed = {"title", "date", "is_done"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return
        cols = ", ".join(f"{k}=?" for k in updates)
        vals = list(updates.values()) + [milestone_id]
        with cls._conn() as c:
            c.execute(f"UPDATE milestones SET {cols} WHERE id=?", vals)

    @classmethod
    def delete_milestone(cls, milestone_id):
        with cls._conn() as c:
            c.execute("DELETE FROM milestones WHERE id=?", (milestone_id,))

    @classmethod
    def get_milestones(cls, project_id):
        with cls._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM milestones WHERE project_id=? ORDER BY date",
                (project_id,),
            ).fetchall()]

    @classmethod
    def get_milestone(cls, milestone_id):
        with cls._conn() as c:
            r = c.execute("SELECT * FROM milestones WHERE id=?",
                          (milestone_id,)).fetchone()
            return dict(r) if r else None

    # ── Notes ──────────────────────────────────────────────────

    @classmethod
    def add_note(cls, date_str, content):
        with cls._conn() as c:
            c.execute("INSERT INTO notes (date, content) VALUES (?,?)",
                      (date_str, content))
            return c.lastrowid

    @classmethod
    def update_note(cls, note_id, content):
        with cls._conn() as c:
            c.execute("UPDATE notes SET content=? WHERE id=?", (content, note_id))

    @classmethod
    def delete_note(cls, note_id):
        with cls._conn() as c:
            c.execute("DELETE FROM notes WHERE id=?", (note_id,))

    @classmethod
    def get_notes_by_date(cls, date_str):
        with cls._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM notes WHERE date=? ORDER BY id", (date_str,)
            ).fetchall()]

    # ── Import / Export ────────────────────────────────────────

    @classmethod
    def export_to_json(cls):
        with cls._conn() as c:
            data = {
                "tasks":      [dict(r) for r in c.execute(
                    "SELECT * FROM tasks").fetchall()],
                "projects":   [dict(r) for r in c.execute(
                    "SELECT * FROM projects").fetchall()],
                "milestones": [dict(r) for r in c.execute(
                    "SELECT * FROM milestones").fetchall()],
                "notes":      [dict(r) for r in c.execute(
                    "SELECT * FROM notes").fetchall()],
            }
        return json.dumps(data, ensure_ascii=False, indent=2)

    @classmethod
    def import_from_json(cls, json_str):
        data = json.loads(json_str)
        with cls._conn() as c:
            for p in data.get("projects", []):
                c.execute(
                    "INSERT OR REPLACE INTO projects"
                    " (id, title, description, start_date, end_date)"
                    " VALUES (?,?,?,?,?)",
                    (p["id"], p["title"], p.get("description", ""),
                     p.get("start_date"), p.get("end_date")),
                )
            for m in data.get("milestones", []):
                c.execute(
                    "INSERT OR REPLACE INTO milestones"
                    " (id, project_id, title, date, is_done)"
                    " VALUES (?,?,?,?,?)",
                    (m["id"], m["project_id"], m["title"],
                     m["date"], m.get("is_done", 0)),
                )
            for t in data.get("tasks", []):
                c.execute(
                    "INSERT OR REPLACE INTO tasks"
                    " (id, title, priority, due_date, is_completed,"
                    "  project_id, milestone_id, created_at)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (t["id"], t["title"], t.get("priority", "low"),
                     t.get("due_date"), t.get("is_completed", 0),
                     t.get("project_id"), t.get("milestone_id"),
                     t.get("created_at",
                           datetime.now().strftime("%Y-%m-%d %H:%M:%S"))),
                )
            for n in data.get("notes", []):
                c.execute(
                    "INSERT OR REPLACE INTO notes (id, date, content)"
                    " VALUES (?,?,?)",
                    (n["id"], n["date"], n["content"]),
                )


# ╔══════════════════════════════════════════════════════════════╗
# ║                     CUSTOM  WIDGETS                         ║
# ╚══════════════════════════════════════════════════════════════╝

class _TouchDelayCard(MDCard):
    """Mixin-style card that detects short vs long press without
    stealing touches from child widgets (checkbox, buttons)."""

    def __init__(self, on_short=None, on_long=None, **kw):
        super().__init__(**kw)
        self._cb_short = on_short
        self._cb_long = on_long
        self._t0 = 0

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            self._t0 = touch.time_start
            # Do NOT grab — let children handle the touch too
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        if self.collide_point(*touch.pos) and self._t0:
            elapsed = touch.time_end - self._t0
            self._t0 = 0
            if elapsed > 0.5 and self._cb_long:
                self._cb_long(self, touch)
                return True
            elif elapsed <= 0.5 and self._cb_short:
                self._cb_short(self)
                return True
        return super().on_touch_up(touch)


class TaskCard(_TouchDelayCard):
    """A single task card used in the Todo board and day-detail lists."""

    task_id    = NumericProperty(0)
    title      = StringProperty("")
    priority   = StringProperty("low")
    completed  = BooleanProperty(False)
    due_date   = StringProperty("")

    def __init__(self, task_data, on_toggle=None, on_long_press=None, **kw):
        self.task_data = task_data
        self.task_id   = task_data["id"]
        self.title     = task_data["title"]
        self.priority  = task_data.get("priority", "low")
        self.completed = bool(task_data.get("is_completed", 0))
        self.due_date  = task_data.get("due_date") or ""
        self._on_toggle_cb = on_toggle
        super().__init__(on_long=on_long_press, **kw)
        self.size_hint_y = None
        self.height      = dp(62)
        self.padding     = dp(8)
        self.radius      = dp(12)
        self.elevation   = 1
        self.md_bg_color = CARD_BG
        self._build()

    def _build(self):
        self.clear_widgets()
        box = MDBoxLayout(orientation="horizontal", spacing=dp(8), padding=dp(4))

        cb = MDCheckbox(active=self.completed, size_hint=(None, 1), width=dp(40))
        cb.bind(active=self._on_check)
        box.add_widget(cb)

        text_box = MDBoxLayout(orientation="vertical", size_hint=(1, 1))
        title_label = MDLabel(
            text=self.title,
            font_style="Body",
            size_hint_y=0.65,
            shorten=True,
            shorten_count=30,
            color=TEXT_PRIMARY if not self.completed else TEXT_SECONDARY,
        )
        if self.completed:
            title_label.text = f"[s]{self.title}[/s]"
            title_label.markup = True
        text_box.add_widget(title_label)

        meta = MDBoxLayout(orientation="horizontal", spacing=dp(4), size_hint_y=0.35)
        dot_color = PRIORITY_COLORS.get(self.priority, TEXT_SECONDARY)
        dot = Widget(size_hint=(None, None), size=(dp(10), dp(10)))
        with dot.canvas:
            Color(*dot_color)
            Ellipse(pos=(0, dp(2)), size=(dp(8), dp(8)))
        meta.add_widget(dot)
        meta.add_widget(MDLabel(
            text="紧急" if self.priority == "urgent" else "普通",
            font_style="Caption", color=TEXT_SECONDARY,
            size_hint_x=None, width=dp(36), padding=[0, dp(2)],
        ))
        if self.due_date:
            meta.add_widget(MDLabel(
                text=self.due_date, font_style="Caption",
                color=TEXT_SECONDARY, shorten=True,
            ))
        text_box.add_widget(meta)
        box.add_widget(text_box)
        self.add_widget(box)

    def _on_check(self, cb, active):
        self.completed = active
        DB.update_task(self.task_id, is_completed=1 if active else 0)
        self._build()
        if self._on_toggle_cb:
            self._on_toggle_cb(self)


class ProjectCard(_TouchDelayCard):
    """Card for the project list screen."""

    project_id   = NumericProperty(0)
    title        = StringProperty("")
    description  = StringProperty("")

    def __init__(self, project_data, on_tap=None, on_long_press=None, **kw):
        self.project_data = project_data
        self.project_id   = project_data["id"]
        self.title        = project_data["title"]
        self.description  = project_data.get("description", "")
        super().__init__(on_short=on_tap, on_long=on_long_press, **kw)
        self.size_hint_y = None
        self.height      = dp(80)
        self.padding     = dp(12)
        self.radius      = dp(12)
        self.elevation   = 1
        self.md_bg_color = CARD_BG

        box = MDBoxLayout(orientation="vertical", spacing=dp(2))
        box.add_widget(MDLabel(
            text=self.title, font_style="Title", size_hint_y=0.5,
            color=TEXT_PRIMARY, shorten=True,
        ))
        desc_text = self.description or "暂无描述"
        box.add_widget(MDLabel(
            text=desc_text, font_style="Body", size_hint_y=0.5,
            color=TEXT_SECONDARY, shorten=True, shorten_count=40,
        ))
        self.add_widget(box)


class TimelineNodeWidget(Widget):
    """A clickable milestone circle + label on the timeline canvas."""

    def __init__(self, milestone, on_select=None, x=0, y=0, w=80, h=90, **kw):
        super().__init__(**kw)
        self.milestone = milestone
        self._on_select = on_select
        self.size_hint = (None, None)
        self.size = (w, h)
        self.pos = (x, y)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            if self._on_select:
                self._on_select(self.milestone)
            return True
        return super().on_touch_down(touch)


class DayCell(ButtonBehavior, BoxLayout):
    """Single day cell in the calendar grid."""

    day_num        = NumericProperty(0)
    date_str       = StringProperty("")
    is_today       = BooleanProperty(False)
    is_other_month = BooleanProperty(False)
    is_selected    = BooleanProperty(False)
    urgent_count   = NumericProperty(0)
    low_count      = NumericProperty(0)

    def __init__(self, on_select=None, **kw):
        super().__init__(**kw)
        self.orientation = "vertical"
        self._on_select  = on_select
        self.size_hint   = (1, 1)
        self._bg_color   = None
        self._bg_rect    = None
        self._canvas_ready = False
        self.bind(pos=self._update_rect, size=self._update_rect)

    def _init_canvas(self):
        if self._canvas_ready:
            return
        self._canvas_ready = True
        with self.canvas.before:
            c = (1, 1, 1, 1)
            if self.is_other_month:
                c = BG_LIGHT
            elif self.is_selected:
                c = get_color_from_hex("#E3F2FD")
            self._bg_color = Color(*c)
            self._bg_rect  = RoundedRectangle(
                pos=self.pos, size=self.size, radius=[dp(6)],
            )

    def _update_rect(self, *a):
        if self._bg_rect:
            self._bg_rect.pos  = self.pos
            self._bg_rect.size = self.size

    def on_release(self):
        if self._on_select and self.date_str:
            self._on_select(self.date_str)

    def build_display(self):
        self.clear_widgets()
        # Day number
        num_color = ACCENT if self.is_today else TEXT_PRIMARY
        if self.is_other_month:
            num_color = TEXT_SECONDARY
        num_label = MDLabel(
            text=str(self.day_num) if self.day_num > 0 else "",
            halign="center", font_style="Body",
            color=num_color, bold=self.is_today,
            size_hint_y=0.5,
        )
        self.add_widget(num_label)

        # Dots
        dots_box = BoxLayout(
            orientation="horizontal", spacing=dp(2),
            size_hint_y=0.35, pos_hint={"center_x": 0.5},
        )
        uc = min(self.urgent_count, 4)
        lc = min(self.low_count, 4 - uc)
        for _ in range(uc):
            d = Widget(size_hint=(None, None), size=(dp(10), dp(10)))
            with d.canvas:
                Color(*PRIORITY_COLORS["urgent"])
                Ellipse(pos=(dp(1), dp(1)), size=(dp(8), dp(8)))
            dots_box.add_widget(d)
        for _ in range(lc):
            d = Widget(size_hint=(None, None), size=(dp(10), dp(10)))
            with d.canvas:
                Color(*PRIORITY_COLORS["low"])
                Ellipse(pos=(dp(1), dp(1)), size=(dp(8), dp(8)))
            dots_box.add_widget(d)
        self.add_widget(dots_box)


# ╔══════════════════════════════════════════════════════════════╗
# ║                   TAB 1 : TODO  DUAL-BOARD                 ║
# ╚══════════════════════════════════════════════════════════════╝

class TodoScreen(MDScreen):

    def __init__(self, app_ref=None, **kw):
        super().__init__(**kw)
        self.app = app_ref
        self.show_completed = False
        self._build()

    def _build(self):
        self.clear_widgets()
        root = MDBoxLayout(orientation="vertical")

        # ── Header ──
        header = self._make_header()
        root.add_widget(header)

        # ── Content ──
        scroll = MDScrollView()
        content = MDBoxLayout(
            orientation="vertical", spacing=dp(8), padding=dp(12),
            size_hint_y=None,
        )
        content.bind(minimum_height=content.setter("height"))

        if self.show_completed:
            self._build_completed_section(content)
        else:
            self._build_section(content, "urgent", "急需做的事")
            content.add_widget(MDDivider(size_hint_y=None, height=dp(1)))
            content.add_widget(Widget(size_hint_y=None, height=dp(8)))
            self._build_section(content, "low", "可能需要做的事")

        scroll.add_widget(content)
        root.add_widget(scroll)
        self.add_widget(root)

    def _make_header(self):
        header = MDBoxLayout(
            orientation="horizontal",
            padding=[dp(16), dp(8), dp(8), dp(8)],
            size_hint_y=None, height=dp(56),
            md_bg_color=CARD_BG,
        )
        header.add_widget(MDLabel(
            text="Todo 看板", font_style="Headline", color=ACCENT,
            size_hint_x=0.55,
        ))

        toggle_btn = MDButton(
            MDButtonText(
                text="查看已完成" if not self.show_completed else "返回待办",
                font_style="Label",
            ),
            style="text" if not self.show_completed else "filled",
            size_hint_x=None, width=dp(100),
            on_release=lambda x: self._toggle_completed(),
        )
        header.add_widget(toggle_btn)

        add_btn = MDIconButton(
            icon="plus", style="standard", theme_icon_color="Custom",
            icon_color=ACCENT, size_hint_x=None, width=dp(48),
            on_release=lambda x: self._show_add_task_dialog(),
        )
        header.add_widget(add_btn)
        return header

    def _build_section(self, container, priority, title):
        color = PRIORITY_COLORS[priority]
        sec_header = MDBoxLayout(orientation="horizontal",
                                  size_hint_y=None, height=dp(36))
        sec_header.add_widget(MDLabel(
            text=title, font_style="Title", color=color,
        ))
        container.add_widget(sec_header)

        tasks = DB.get_tasks_by_priority(priority)
        if not tasks:
            container.add_widget(MDLabel(
                text="  暂无任务", font_style="Body",
                color=TEXT_SECONDARY, size_hint_y=None, height=dp(36),
            ))
        for t in tasks:
            card = TaskCard(
                t, on_toggle=self._refresh_after,
                on_long_press=self._task_long_press,
            )
            container.add_widget(card)

    def _build_completed_section(self, container):
        sec_header = MDBoxLayout(orientation="horizontal",
                                  size_hint_y=None, height=dp(36))
        sec_header.add_widget(MDLabel(
            text="已完成的任务", font_style="Title", color=GREEN_DONE,
        ))
        container.add_widget(sec_header)

        tasks = DB.get_completed_tasks()
        if not tasks:
            container.add_widget(MDLabel(
                text="  暂无已完成任务", font_style="Body",
                color=TEXT_SECONDARY, size_hint_y=None, height=dp(36),
            ))
        for t in tasks:
            card = TaskCard(
                t, on_toggle=self._uncomplete_task,
                on_long_press=self._task_long_press,
            )
            container.add_widget(card)

    def _toggle_completed(self):
        self.show_completed = not self.show_completed
        self._build()

    def _uncomplete_task(self, card):
        DB.update_task(card.task_id, is_completed=0)
        self._build()

    def _refresh_after(self, card):
        Clock.schedule_once(lambda dt: self._build(), 0.4)

    # ── Long press menu ────────────────────────────────────────

    def _task_long_press(self, card, touch):
        menu_items = [
            ("编辑标题", lambda: self._edit_task(card)),
            ("删除任务", lambda: self._delete_task(card)),
            ("设为紧急" if card.priority != "urgent" else "设为普通",
             lambda: self._toggle_priority(card)),
            ("移动到项目", lambda: self._move_to_project(card)),
        ]
        self._show_popup_menu(menu_items)

    def _show_popup_menu(self, items):
        content = MDBoxLayout(orientation="vertical", spacing=dp(2),
                               padding=dp(8), size_hint_y=None,
                               height=dp(len(items) * 44 + 16))
        for label, action in items:
            btn = MDButton(
                MDButtonText(text=label),
                style="text", size_hint_y=None, height=dp(44),
                on_release=lambda x, a=action: self._dismiss_and(a()),
            )
            content.add_widget(btn)
        self._popup = MDDialog(
            MDDialogContentContainer(content),
            size_hint_x=0.72, size_hint_y=None,
            height=dp(len(items) * 48 + 24),
        )
        self._popup.open()

    def _dismiss_and(self, action):
        if hasattr(self, "_popup") and self._popup:
            self._popup.dismiss()
        action()

    def _edit_task(self, card):
        self._show_edit_task_dialog(card)

    def _delete_task(self, card):
        DB.delete_task(card.task_id)
        self._build()

    def _toggle_priority(self, card):
        new_p = "urgent" if card.priority != "urgent" else "low"
        DB.update_task(card.task_id, priority=new_p)
        self._build()

    def _move_to_project(self, card):
        projects = DB.get_all_projects()
        if not projects:
            MDSnackbar(
                MDSnackbarText(text="暂无项目，请先在项目 Tab 中创建"),
                y=dp(24),
            ).open()
            return
        items = [
            (p["title"], (lambda pid=p["id"]: self._do_move(card, pid)))
            for p in projects
        ]
        self._show_popup_menu(items)

    def _do_move(self, card, project_id):
        DB.update_task(card.task_id, project_id=project_id)
        MDSnackbar(MDSnackbarText(text="已移动到项目"), y=dp(24)).open()
        self._build()

    # ── Add task dialog ────────────────────────────────────────

    def _show_add_task_dialog(self):
        content = MDBoxLayout(orientation="vertical", spacing=dp(12),
                               padding=dp(12), size_hint_y=None, height=dp(240))
        title_field = MDTextField(
            MDTextFieldHintText(text="任务标题"),
            mode="outlined", size_hint_y=None, height=dp(52),
        )

        self._add_priority = "low"
        p_box = MDBoxLayout(orientation="horizontal", spacing=dp(8),
                             size_hint_y=None, height=dp(40))
        p_box.add_widget(MDLabel(text="优先级:", size_hint_x=None, width=dp(60)))
        urgent_chip = MDChip(
            MDChipText(text="紧急"), type="choice",
            active=False, size_hint_x=None, width=dp(64),
            on_release=lambda x: self._set_chip_priority("urgent", urgent_chip, low_chip),
        )
        low_chip = MDChip(
            MDChipText(text="普通"), type="choice",
            active=True, size_hint_x=None, width=dp(64),
            on_release=lambda x: self._set_chip_priority("low", urgent_chip, low_chip),
        )
        p_box.add_widget(urgent_chip)
        p_box.add_widget(low_chip)
        content.add_widget(title_field)
        content.add_widget(p_box)

        self._add_due_date = ""
        date_lbl = MDLabel(text="截止日期: (可选)", font_style="Body",
                            color=TEXT_SECONDARY)
        date_row = MDBoxLayout(orientation="horizontal", spacing=dp(8),
                                size_hint_y=None, height=dp(40))
        date_row.add_widget(date_lbl)
        date_btn = MDButton(
            MDButtonText(text="选择日期"), style="outlined",
            size_hint_x=None, width=dp(100),
            on_release=lambda x: self._pick_date(date_lbl),
        )
        date_row.add_widget(date_btn)
        content.add_widget(date_row)

        self._add_dialog = MDDialog(
            MDDialogHeadlineText(text="新建任务"),
            MDDialogContentContainer(content),
            MDDialogButtonContainer(
                MDFlatButton(text="取消",
                             on_release=lambda x: self._add_dialog.dismiss()),
                MDRaisedButton(text="确定",
                               on_release=lambda x: self._do_add_task(
                                   title_field.text.strip())),
                spacing=dp(16),
            ),
            size_hint_x=0.9,
        )
        self._add_dialog.open()

    def _set_chip_priority(self, val, chip_a, chip_b):
        self._add_priority = val
        chip_a.active = (val == "urgent")
        chip_b.active = (val == "low")

    def _pick_date(self, label):
        picker = MDDatePicker()
        picker.bind(on_save=lambda inst, val, _: self._on_date_picked(val, label))
        picker.open()

    def _on_date_picked(self, val, label):
        self._add_due_date = val.isoformat()
        label.text = f"截止日期: {self._add_due_date}"
        label.color = TEXT_PRIMARY

    def _do_add_task(self, title):
        if not title:
            return
        DB.add_task(title, priority=self._add_priority,
                    due_date=self._add_due_date or None)
        self._add_dialog.dismiss()
        self._build()

    # ── Edit task dialog ───────────────────────────────────────

    def _show_edit_task_dialog(self, card):
        content = MDBoxLayout(orientation="vertical", spacing=dp(12),
                               padding=dp(12), size_hint_y=None, height=dp(100))
        tf = MDTextField(
            MDTextFieldHintText(text=card.title),
            text=card.title,
            mode="outlined", size_hint_y=None, height=dp(52),
        )
        content.add_widget(tf)

        self._edit_dialog = MDDialog(
            MDDialogHeadlineText(text="编辑任务"),
            MDDialogContentContainer(content),
            MDDialogButtonContainer(
                MDFlatButton(text="取消",
                             on_release=lambda x: self._edit_dialog.dismiss()),
                MDRaisedButton(text="保存",
                               on_release=lambda x: self._do_edit_task(
                                   card, tf.text.strip())),
                spacing=dp(16),
            ),
            size_hint_x=0.9,
        )
        self._edit_dialog.open()

    def _do_edit_task(self, card, new_title):
        if not new_title:
            return
        DB.update_task(card.task_id, title=new_title)
        self._edit_dialog.dismiss()
        self._build()

    def refresh(self):
        self._build()


# ╔══════════════════════════════════════════════════════════════╗
# ║              TAB 2 : PROJECT  WORKFLOW  TIMELINE           ║
# ╚══════════════════════════════════════════════════════════════╝

class TimelineCanvas(ScrollView):
    """Horizontal scrollable timeline with canvas-drawn nodes."""

    def __init__(self, on_select_node=None, **kw):
        super().__init__(**kw)
        self.do_scroll_y = False
        self.do_scroll_x = True
        self.bar_width  = dp(4)
        self.size_hint_y = None
        self.height      = dp(170)
        self._on_select  = on_select_node
        self._canvas_widget = None

    def build(self, milestones):
        self.clear_widgets()
        if not milestones:
            empty = MDLabel(
                text="暂无里程碑\n点击 + 添加", halign="center",
                font_style="Body", color=TEXT_SECONDARY,
                size_hint_x=None, width=dp(300),
            )
            self.add_widget(empty)
            return

        today = date.today()
        today_dt = datetime(today.year, today.month, today.day)

        # Determine date range
        dts = []
        for m in milestones:
            try:
                dts.append(datetime.strptime(m["date"], "%Y-%m-%d"))
            except (ValueError, TypeError):
                pass
        if not dts:
            return
        all_dts = dts + [today_dt]
        min_d = min(all_dts) - timedelta(days=1)
        max_d = max(all_dts) + timedelta(days=1)
        day_span = (max_d - min_d).days
        if day_span < 14:
            day_span = 14

        px_per_day = dp(46)
        pad_x      = dp(40)
        content_w  = pad_x * 2 + day_span * px_per_day
        line_y     = dp(90)

        self._canvas_widget = Widget(size=(content_w, dp(160)))
        self.add_widget(self._canvas_widget)

        # Draw base line
        with self._canvas_widget.canvas:
            Color(*DIVIDER_COLOR)
            Line(points=[pad_x, line_y, content_w - pad_x, line_y], width=dp(2))

        # Today vertical marker
        today_offset = (today_dt - min_d).days
        today_x = pad_x + today_offset * px_per_day
        with self._canvas_widget.canvas:
            Color(*ACCENT_LIGHT)
            Line(points=[today_x, line_y - dp(40), today_x, line_y + dp(40)],
                 width=dp(2), dash_offset=2)

        # Today label
        from kivy.uix.label import Label as KivyLabel
        tl = KivyLabel(
            text="今天", color=ACCENT_LIGHT, font_size=sp(11),
            size_hint=(None, None), size=(dp(36), dp(16)),
            halign="center", valign="middle",
            pos=(today_x - dp(18), line_y + dp(42)),
        )
        self._canvas_widget.add_widget(tl)

        # Milestone nodes — alternate above and below the line
        for idx, m in enumerate(milestones):
            try:
                m_dt = datetime.strptime(m["date"], "%Y-%m-%d")
            except (ValueError, TypeError):
                continue
            offset = (m_dt - min_d).days
            cx = pad_x + offset * px_per_day

            # Alternate above / below
            above = (idx % 2 == 0)
            ny = line_y + dp(18) if above else line_y - dp(60)

            # Circle on the line
            is_done = bool(m.get("is_done", 0))
            circle_color = GREEN_DONE if is_done else ACCENT
            with self._canvas_widget.canvas:
                Color(*circle_color)
                Ellipse(pos=(cx - dp(8), line_y - dp(8)), size=(dp(16), dp(16)))

            # Date label
            date_text = m["date"][5:] if len(m["date"]) > 5 else m["date"]
            dl = KivyLabel(
                text=date_text, color=TEXT_SECONDARY, font_size=sp(10),
                size_hint=(None, None), size=(dp(60), dp(14)),
                halign="center", pos=(cx - dp(30), ny + dp(40) if above else ny - dp(14)),
            )
            self._canvas_widget.add_widget(dl)

            # Title label (clickable)
            title_short = m["title"][:10]
            tw = max(dp(80), len(title_short) * dp(10))
            tl_widget = KivyLabel(
                text=title_short, color=TEXT_PRIMARY, font_size=sp(12),
                size_hint=(None, None), size=(tw, dp(18)),
                halign="center", bold=True,
                pos=(cx - tw / 2, ny + dp(24) if above else ny - dp(30)),
            )
            self._canvas_widget.add_widget(tl_widget)

            # Invisible button for tap detection
            tap_btn = Button(
                text="", background_color=(0, 0, 0, 0),
                size_hint=(None, None),
                size=(dp(70), dp(60)),
                pos=(cx - dp(35), ny + dp(8) if above else ny - dp(10)),
                on_release=lambda btn, mm=m: self._on_node_tap(mm),
            )
            self._canvas_widget.add_widget(tap_btn)

    def _on_node_tap(self, milestone):
        if self._on_select:
            self._on_select(milestone)


class ProjectScreen(MDScreen):

    def __init__(self, app_ref=None, **kw):
        super().__init__(**kw)
        self.app = app_ref
        self._detail_mode      = False
        self._current_project  = None
        self._selected_milestone = None
        self._build()

    def _build(self):
        self.clear_widgets()
        if self._detail_mode and self._current_project:
            self._build_detail()
        else:
            self._build_list()

    # ── Project list view ──────────────────────────────────────

    def _build_list(self):
        root = MDBoxLayout(orientation="vertical")

        header = MDBoxLayout(
            orientation="horizontal",
            padding=[dp(16), dp(8), dp(8), dp(8)],
            size_hint_y=None, height=dp(56), md_bg_color=CARD_BG,
        )
        header.add_widget(MDLabel(
            text="项目", font_style="Headline", color=ACCENT,
        ))
        header.add_widget(MDIconButton(
            icon="plus", style="standard", theme_icon_color="Custom",
            icon_color=ACCENT, size_hint_x=None, width=dp(48),
            on_release=lambda x: self._show_add_project_dialog(),
        ))
        root.add_widget(header)

        scroll = MDScrollView()
        content = MDBoxLayout(orientation="vertical", spacing=dp(8),
                               padding=dp(12), size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))

        projects = DB.get_all_projects()
        if not projects:
            content.add_widget(MDLabel(
                text="暂无项目\n点击 + 创建新项目", halign="center",
                font_style="Body", color=TEXT_SECONDARY,
                size_hint_y=None, height=dp(80),
            ))
        for p in projects:
            card = ProjectCard(
                p, on_tap=self._open_project,
                on_long_press=self._project_long_press,
            )
            content.add_widget(card)

        scroll.add_widget(content)
        root.add_widget(scroll)
        self.add_widget(root)

    # ── Project detail view ────────────────────────────────────

    def _build_detail(self):
        p = self._current_project
        if not p:
            return
        root = MDBoxLayout(orientation="vertical")

        # Header
        header = MDBoxLayout(
            orientation="horizontal",
            padding=[dp(4), dp(8), dp(8), dp(8)],
            size_hint_y=None, height=dp(56), md_bg_color=CARD_BG,
        )
        header.add_widget(MDIconButton(
            icon="arrow-left", style="standard",
            size_hint_x=None, width=dp(48),
            on_release=lambda x: self._go_back(),
        ))
        header.add_widget(MDLabel(
            text=p["title"], font_style="Headline", color=ACCENT,
            shorten=True, size_hint_x=0.5,
        ))
        header.add_widget(MDIconButton(
            icon="plus", style="standard", theme_icon_color="Custom",
            icon_color=ACCENT, size_hint_x=None, width=dp(48),
            on_release=lambda x: self._show_add_milestone_dialog(),
        ))
        root.add_widget(header)

        # Date info
        parts = []
        if p.get("start_date"):
            parts.append(f"开始: {p['start_date']}")
        if p.get("end_date"):
            parts.append(f"结束: {p['end_date']}")
        if parts:
            info = MDBoxLayout(orientation="horizontal", size_hint_y=None,
                                height=dp(24), padding=[dp(16), 0])
            info.add_widget(MDLabel(
                text="  ".join(parts), font_style="Caption",
                color=TEXT_SECONDARY,
            ))
            root.add_widget(info)
        root.add_widget(MDDivider(size_hint_y=None, height=dp(1)))

        # Timeline
        milestones = DB.get_milestones(p["id"])
        timeline = TimelineCanvas(on_select_node=self._on_milestone_select)
        timeline.build(milestones)
        root.add_widget(timeline)
        root.add_widget(MDDivider(size_hint_y=None, height=dp(1)))

        # Milestone detail / task list section
        detail_area = self._build_milestone_detail(p)
        root.add_widget(detail_area)
        self.add_widget(root)

    def _build_milestone_detail(self, project):
        container = MDBoxLayout(orientation="vertical")

        # Toolbar
        bar = MDBoxLayout(orientation="horizontal", size_hint_y=None,
                           height=dp(40), padding=[dp(12), dp(4)])
        if self._selected_milestone:
            ms = self._selected_milestone
            bar.add_widget(MDLabel(
                text=f"节点: {ms['title']}", font_style="Title",
                color=TEXT_PRIMARY, size_hint_x=0.5,
            ))
            done_text = "标记完成" if not ms.get("is_done", 0) else "取消完成"
            bar.add_widget(MDButton(
                MDButtonText(text=done_text, font_style="Label"),
                style="outlined", size_hint_x=None, width=dp(90),
                on_release=lambda x: self._toggle_milestone_done(),
            ))
            bar.add_widget(MDIconButton(
                icon="plus", style="standard", theme_icon_color="Custom",
                icon_color=ACCENT, size_hint_x=None, width=dp(36),
                on_release=lambda x: self._show_add_milestone_task_dialog(),
            ))
        else:
            bar.add_widget(MDLabel(
                text="点击上方节点查看任务", font_style="Body",
                color=TEXT_SECONDARY,
            ))
        container.add_widget(bar)

        # Task list
        scroll = MDScrollView()
        content = MDBoxLayout(orientation="vertical", spacing=dp(4),
                               padding=dp(12), size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))

        if self._selected_milestone:
            tasks = DB.get_tasks_by_milestone(self._selected_milestone["id"])
        else:
            tasks = DB.get_tasks_by_project(project["id"])

        if not tasks:
            content.add_widget(MDLabel(
                text="  暂无任务", font_style="Body", color=TEXT_SECONDARY,
                size_hint_y=None, height=dp(36),
            ))
        for t in tasks:
            card = TaskCard(t, on_toggle=self._refresh_detail,
                            on_long_press=self._milestone_task_long_press)
            content.add_widget(card)

        scroll.add_widget(content)
        container.add_widget(scroll)
        return container

    def _open_project(self, card):
        self._current_project = DB.get_project(card.project_id)
        self._selected_milestone = None
        self._detail_mode = True
        self._build()

    def _go_back(self):
        self._detail_mode = False
        self._current_project = None
        self._selected_milestone = None
        self._build()

    def _project_long_press(self, card, touch):
        self._show_popup_menu([
            ("编辑项目", lambda: self._edit_project(card)),
            ("删除项目", lambda: self._delete_project(card)),
        ])

    def _show_popup_menu(self, items):
        content = MDBoxLayout(orientation="vertical", spacing=dp(2),
                               padding=dp(8), size_hint_y=None,
                               height=dp(len(items) * 44 + 16))
        for label, action in items:
            btn = MDButton(
                MDButtonText(text=label),
                style="text", size_hint_y=None, height=dp(44),
                on_release=lambda x, a=action: self._dismiss_and(a),
            )
            content.add_widget(btn)
        self._popup = MDDialog(
            MDDialogContentContainer(content),
            size_hint_x=0.72, size_hint_y=None,
            height=dp(len(items) * 48 + 24),
        )
        self._popup.open()

    def _dismiss_and(self, action):
        if hasattr(self, "_popup") and self._popup:
            self._popup.dismiss()
        action()

    def _delete_project(self, card):
        DB.delete_project(card.project_id)
        self._build()

    def _edit_project(self, card):
        p = DB.get_project(card.project_id)
        if not p:
            return
        content = MDBoxLayout(orientation="vertical", spacing=dp(12),
                               padding=dp(12), size_hint_y=None, height=dp(160))
        tf_title = MDTextField(
            MDTextFieldHintText(text="项目名称"),
            text=p["title"], mode="outlined",
            size_hint_y=None, height=dp(52),
        )
        tf_desc = MDTextField(
            MDTextFieldHintText(text="描述"),
            text=p.get("description", ""), mode="outlined",
            size_hint_y=None, height=dp(52),
        )
        content.add_widget(tf_title)
        content.add_widget(tf_desc)

        self._edit_dialog = MDDialog(
            MDDialogHeadlineText(text="编辑项目"),
            MDDialogContentContainer(content),
            MDDialogButtonContainer(
                MDFlatButton(text="取消",
                             on_release=lambda x: self._edit_dialog.dismiss()),
                MDRaisedButton(text="保存",
                               on_release=lambda x: self._do_edit_project(
                                   p["id"], tf_title.text.strip(),
                                   tf_desc.text.strip())),
                spacing=dp(16),
            ),
            size_hint_x=0.9,
        )
        self._edit_dialog.open()

    def _do_edit_project(self, pid, title, desc):
        if not title:
            return
        DB.update_project(pid, title=title, description=desc)
        self._edit_dialog.dismiss()
        self._build()

    # ── Add project ────────────────────────────────────────────

    def _show_add_project_dialog(self):
        content = MDBoxLayout(orientation="vertical", spacing=dp(12),
                               padding=dp(12), size_hint_y=None, height=dp(200))
        tf_title = MDTextField(
            MDTextFieldHintText(text="项目名称"),
            mode="outlined", size_hint_y=None, height=dp(52),
        )
        tf_desc = MDTextField(
            MDTextFieldHintText(text="描述 (可选)"),
            mode="outlined", size_hint_y=None, height=dp(52),
        )
        content.add_widget(tf_title)
        content.add_widget(tf_desc)

        self._proj_start = ""
        self._proj_end   = ""
        date_row = MDBoxLayout(orientation="horizontal", spacing=dp(6),
                                size_hint_y=None, height=dp(40))
        s_lbl = MDLabel(text="开始:", size_hint_x=None, width=dp(36))
        s_btn = MDButton(
            MDButtonText(text="选"), style="outlined",
            size_hint_x=None, width=dp(44),
            on_release=lambda x: self._pick_proj_date("start", s_lbl),
        )
        e_lbl = MDLabel(text="结束:", size_hint_x=None, width=dp(36))
        e_btn = MDButton(
            MDButtonText(text="选"), style="outlined",
            size_hint_x=None, width=dp(44),
            on_release=lambda x: self._pick_proj_date("end", e_lbl),
        )
        date_row.add_widget(s_lbl)
        date_row.add_widget(s_btn)
        date_row.add_widget(e_lbl)
        date_row.add_widget(e_btn)
        content.add_widget(date_row)

        self._add_dialog = MDDialog(
            MDDialogHeadlineText(text="新建项目"),
            MDDialogContentContainer(content),
            MDDialogButtonContainer(
                MDFlatButton(text="取消",
                             on_release=lambda x: self._add_dialog.dismiss()),
                MDRaisedButton(text="确定",
                               on_release=lambda x: self._do_add_project(
                                   tf_title.text.strip(),
                                   tf_desc.text.strip())),
                spacing=dp(16),
            ),
            size_hint_x=0.9,
        )
        self._add_dialog.open()

    def _pick_proj_date(self, which, label):
        picker = MDDatePicker()
        picker.bind(on_save=lambda inst, val, _: self._on_proj_date(val, which, label))
        picker.open()

    def _on_proj_date(self, val, which, label):
        ds = val.isoformat()
        if which == "start":
            self._proj_start = ds
        else:
            self._proj_end = ds
        label.text = f"{'开始' if which == 'start' else '结束'}: {ds[5:]}"

    def _do_add_project(self, title, desc):
        if not title:
            return
        DB.add_project(title, desc, self._proj_start or None,
                       self._proj_end or None)
        self._add_dialog.dismiss()
        self._build()

    # ── Milestone operations ───────────────────────────────────

    def _show_add_milestone_dialog(self):
        if not self._current_project:
            return
        content = MDBoxLayout(orientation="vertical", spacing=dp(12),
                               padding=dp(12), size_hint_y=None, height=dp(160))
        tf = MDTextField(
            MDTextFieldHintText(text="里程碑标题"),
            mode="outlined", size_hint_y=None, height=dp(52),
        )
        content.add_widget(tf)

        self._ms_date = date.today().isoformat()
        d_lbl = MDLabel(text=f"日期: {self._ms_date}", font_style="Body")
        d_btn = MDButton(
            MDButtonText(text="选择日期"), style="outlined",
            on_release=lambda x: self._pick_ms_date(d_lbl),
        )
        d_row = MDBoxLayout(orientation="horizontal", spacing=dp(8),
                             size_hint_y=None, height=dp(40))
        d_row.add_widget(d_lbl)
        d_row.add_widget(d_btn)
        content.add_widget(d_row)

        self._add_dialog = MDDialog(
            MDDialogHeadlineText(text="添加里程碑"),
            MDDialogContentContainer(content),
            MDDialogButtonContainer(
                MDFlatButton(text="取消",
                             on_release=lambda x: self._add_dialog.dismiss()),
                MDRaisedButton(text="确定",
                               on_release=lambda x: self._do_add_milestone(
                                   tf.text.strip())),
                spacing=dp(16),
            ),
            size_hint_x=0.9,
        )
        self._add_dialog.open()

    def _pick_ms_date(self, label):
        picker = MDDatePicker()
        picker.bind(on_save=lambda inst, val, _: self._on_ms_date(val, label))
        picker.open()

    def _on_ms_date(self, val, label):
        self._ms_date = val.isoformat()
        label.text = f"日期: {self._ms_date}"

    def _do_add_milestone(self, title):
        if not title or not self._current_project:
            return
        DB.add_milestone(self._current_project["id"], title, self._ms_date)
        self._add_dialog.dismiss()
        self._build()

    def _on_milestone_select(self, data):
        self._selected_milestone = data
        self._build()

    def _toggle_milestone_done(self):
        if not self._selected_milestone:
            return
        current = self._selected_milestone.get("is_done", 0)
        new_val = 0 if current else 1
        DB.update_milestone(self._selected_milestone["id"], is_done=new_val)
        self._selected_milestone["is_done"] = new_val
        self._build()

    # ── Milestone tasks ────────────────────────────────────────

    def _show_add_milestone_task_dialog(self):
        if not self._selected_milestone or not self._current_project:
            return
        content = MDBoxLayout(orientation="vertical", spacing=dp(12),
                               padding=dp(12), size_hint_y=None, height=dp(180))
        tf = MDTextField(
            MDTextFieldHintText(text="任务标题"),
            mode="outlined", size_hint_y=None, height=dp(52),
        )
        content.add_widget(tf)

        self._ms_task_priority = "low"
        p_row = MDBoxLayout(orientation="horizontal", spacing=dp(8),
                             size_hint_y=None, height=dp(40))
        p_row.add_widget(MDLabel(text="优先级:", size_hint_x=None, width=dp(60)))
        u_chip = MDChip(MDChipText(text="紧急"), type="choice",
                         active=False, size_hint_x=None, width=dp(60))
        l_chip = MDChip(MDChipText(text="普通"), type="choice",
                         active=True, size_hint_x=None, width=dp(60))
        u_chip.bind(on_release=lambda x: self._set_task_priority("urgent", u_chip, l_chip))
        l_chip.bind(on_release=lambda x: self._set_task_priority("low", u_chip, l_chip))
        p_row.add_widget(u_chip)
        p_row.add_widget(l_chip)
        content.add_widget(p_row)

        self._ms_task_date = self._selected_milestone.get("date", "")
        d_lbl = MDLabel(text=f"截止: {self._ms_task_date or '无'}",
                         font_style="Body")
        content.add_widget(d_lbl)

        self._add_dialog = MDDialog(
            MDDialogHeadlineText(text="添加任务到节点"),
            MDDialogContentContainer(content),
            MDDialogButtonContainer(
                MDFlatButton(text="取消",
                             on_release=lambda x: self._add_dialog.dismiss()),
                MDRaisedButton(text="确定",
                               on_release=lambda x: self._do_add_ms_task(
                                   tf.text.strip())),
                spacing=dp(16),
            ),
            size_hint_x=0.9,
        )
        self._add_dialog.open()

    def _set_task_priority(self, val, chip_u, chip_l):
        self._ms_task_priority = val
        chip_u.active = (val == "urgent")
        chip_l.active = (val == "low")

    def _do_add_ms_task(self, title):
        if not title:
            return
        DB.add_task(
            title, priority=self._ms_task_priority,
            due_date=self._ms_task_date or None,
            project_id=self._current_project["id"],
            milestone_id=self._selected_milestone["id"],
        )
        self._add_dialog.dismiss()
        self._build()

    def _milestone_task_long_press(self, card, touch):
        self._show_popup_menu([
            ("编辑标题", lambda: self._ms_edit_task(card)),
            ("删除任务", lambda: self._ms_delete_task(card)),
            ("切换优先级", lambda: self._ms_toggle_priority(card)),
        ])

    def _ms_edit_task(self, card):
        content = MDBoxLayout(orientation="vertical", spacing=dp(12),
                               padding=dp(12), size_hint_y=None, height=dp(100))
        tf = MDTextField(text=card.title, mode="outlined",
                          size_hint_y=None, height=dp(52))
        content.add_widget(tf)
        self._edit_dialog = MDDialog(
            MDDialogHeadlineText(text="编辑任务"),
            MDDialogContentContainer(content),
            MDDialogButtonContainer(
                MDFlatButton(text="取消",
                             on_release=lambda x: self._edit_dialog.dismiss()),
                MDRaisedButton(text="保存",
                               on_release=lambda x: self._ms_do_edit(card, tf.text.strip())),
                spacing=dp(16),
            ),
            size_hint_x=0.9,
        )
        self._edit_dialog.open()

    def _ms_do_edit(self, card, new_title):
        if not new_title:
            return
        DB.update_task(card.task_id, title=new_title)
        self._edit_dialog.dismiss()
        self._build()

    def _ms_delete_task(self, card):
        DB.delete_task(card.task_id)
        self._build()

    def _ms_toggle_priority(self, card):
        new_p = "urgent" if card.priority != "urgent" else "low"
        DB.update_task(card.task_id, priority=new_p)
        self._build()

    def _refresh_detail(self, card):
        Clock.schedule_once(lambda dt: self._build(), 0.3)

    def refresh(self):
        self._detail_mode = False
        self._current_project = None
        self._selected_milestone = None
        self._build()


# ╔══════════════════════════════════════════════════════════════╗
# ║                  TAB 3 : CALENDAR  VIEW                    ║
# ╚══════════════════════════════════════════════════════════════╝

class CalendarScreen(MDScreen):

    def __init__(self, app_ref=None, **kw):
        super().__init__(**kw)
        self.app = app_ref
        self.today          = date.today()
        self.current_year   = self.today.year
        self.current_month  = self.today.month
        self.selected_date  = self.today.isoformat()
        self._day_widgets   = []
        self._swipe_start_x = 0
        self._build()

    def _build(self):
        self.clear_widgets()
        self._day_widgets = []
        root = MDBoxLayout(orientation="vertical")

        # ── Month header ──
        header = MDBoxLayout(
            orientation="horizontal",
            padding=[dp(8), dp(8), dp(8), dp(8)],
            size_hint_y=None, height=dp(56), md_bg_color=CARD_BG,
        )
        header.add_widget(MDIconButton(
            icon="chevron-left", size_hint_x=None, width=dp(40),
            on_release=lambda x: self._change_month(-1),
        ))
        header.add_widget(MDLabel(
            text=f"{self.current_year}年 {self.current_month}月",
            font_style="Headline", color=ACCENT,
            halign="center", size_hint_x=1,
        ))
        header.add_widget(MDIconButton(
            icon="chevron-right", size_hint_x=None, width=dp(40),
            on_release=lambda x: self._change_month(1),
        ))
        root.add_widget(header)

        # ── Day-of-week bar ──
        dow_header = MDBoxLayout(orientation="horizontal",
                                  size_hint_y=None, height=dp(26),
                                  padding=[dp(4), 0])
        for i, d in enumerate(["一", "二", "三", "四", "五", "六", "日"]):
            c = ACCENT if d in ("六", "日") else TEXT_SECONDARY
            dow_header.add_widget(MDLabel(
                text=d, halign="center", font_style="Caption", color=c,
            ))
        root.add_widget(dow_header)

        # ── Calendar grid ──
        grid_container = MDBoxLayout(orientation="vertical",
                                      padding=[dp(4), 0, dp(4), dp(8)],
                                      size_hint_y=None, height=dp(300))
        grid = GridLayout(cols=7, spacing=dp(2), size_hint_y=None, height=dp(290))

        task_map = DB.get_all_tasks_grouped_by_date(
            self.current_year, self.current_month,
        )

        first_weekday, num_days = monthrange(self.current_year, self.current_month)
        # Python: 0=Monday, 6=Sunday

        cells_to_build = []

        # Previous month padding
        if first_weekday > 0:
            pm = self.current_month - 1 if self.current_month > 1 else 12
            py = self.current_year if self.current_month > 1 else self.current_year - 1
            _, pd_num = monthrange(py, pm)
            for i in range(first_weekday):
                day = pd_num - first_weekday + i + 1
                ds = f"{py:04d}-{pm:02d}-{day:02d}"
                tasks = task_map.get(ds, [])
                cells_to_build.append((
                    day, ds, False, True,
                    sum(1 for t in tasks if t["priority"] == "urgent"),
                    sum(1 for t in tasks if t["priority"] == "low"),
                ))

        # Current month
        for day in range(1, num_days + 1):
            ds = f"{self.current_year:04d}-{self.current_month:02d}-{day:02d}"
            is_today = (ds == self.today.isoformat())
            tasks = task_map.get(ds, [])
            cells_to_build.append((
                day, ds, is_today, False,
                sum(1 for t in tasks if t["priority"] == "urgent"),
                sum(1 for t in tasks if t["priority"] == "low"),
            ))

        # Next month padding
        remaining = 42 - len(cells_to_build)
        nm = self.current_month + 1 if self.current_month < 12 else 1
        ny = self.current_year if self.current_month < 12 else self.current_year + 1
        for i in range(remaining):
            day = i + 1
            ds = f"{ny:04d}-{nm:02d}-{day:02d}"
            tasks = task_map.get(ds, [])
            cells_to_build.append((
                day, ds, False, True,
                sum(1 for t in tasks if t["priority"] == "urgent"),
                sum(1 for t in tasks if t["priority"] == "low"),
            ))

        for (day, ds, is_t, is_om, uc, lc) in cells_to_build:
            cell = DayCell(on_select=self._on_day_select)
            cell.day_num        = day
            cell.date_str       = ds
            cell.is_today       = is_t
            cell.is_other_month = is_om
            cell.is_selected    = (ds == self.selected_date)
            cell.urgent_count   = uc
            cell.low_count      = lc
            cell._init_canvas()
            cell.build_display()
            grid.add_widget(cell)
            self._day_widgets.append(cell)

        grid_container.add_widget(grid)

        # Wrap grid in ScrollView for small screens
        cal_scroll = MDScrollView(do_scroll_x=False, do_scroll_y=True)
        cal_scroll.add_widget(grid_container)
        root.add_widget(cal_scroll)

        root.add_widget(MDDivider(size_hint_y=None, height=dp(1)))

        # ── Selected day detail ──
        self._build_day_detail(root)

        self.add_widget(root)

    def _build_day_detail(self, root):
        # Header row
        detail_bar = MDBoxLayout(orientation="horizontal",
                                  size_hint_y=None, height=dp(40),
                                  padding=[dp(12), dp(4)])
        detail_bar.add_widget(MDLabel(
            text=f"{self.selected_date} 详情", font_style="Title",
            color=TEXT_PRIMARY, size_hint_x=0.5,
        ))
        detail_bar.add_widget(MDIconButton(
            icon="note-plus", style="standard",
            theme_icon_color="Custom", icon_color=ACCENT,
            size_hint_x=None, width=dp(40),
            on_release=lambda x: self._show_add_note_dialog(),
        ))
        detail_bar.add_widget(MDIconButton(
            icon="calendar-plus", style="standard",
            theme_icon_color="Custom", icon_color=ACCENT,
            size_hint_x=None, width=dp(40),
            on_release=lambda x: self._show_calendar_add_task_dialog(),
        ))
        root.add_widget(detail_bar)

        # Scrollable detail
        scroll = MDScrollView()
        content = MDBoxLayout(orientation="vertical", spacing=dp(4),
                               padding=dp(12), size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))

        # Tasks
        tasks = DB.get_tasks_by_date(self.selected_date)
        if tasks:
            content.add_widget(MDLabel(
                text="任务:", font_style="Label", color=TEXT_SECONDARY,
                size_hint_y=None, height=dp(22),
            ))
            for t in tasks:
                card = TaskCard(t, on_toggle=self._refresh_after,
                                on_long_press=self._calendar_task_long_press)
                content.add_widget(card)
        else:
            content.add_widget(MDLabel(
                text="  该日无任务", font_style="Body", color=TEXT_SECONDARY,
                size_hint_y=None, height=dp(28),
            ))

        # Notes
        notes = DB.get_notes_by_date(self.selected_date)
        content.add_widget(MDLabel(
            text="备注:", font_style="Label", color=TEXT_SECONDARY,
            size_hint_y=None, height=dp(22),
        ))
        if notes:
            for n in notes:
                note_card = MDCard(
                    size_hint_y=None, height=dp(48), padding=dp(8),
                    radius=dp(8), md_bg_color=CARD_BG, elevation=1,
                )
                nb = MDBoxLayout(orientation="horizontal")
                nb.add_widget(MDLabel(
                    text=n["content"], font_style="Body",
                    color=TEXT_PRIMARY,
                ))
                nb.add_widget(MDIconButton(
                    icon="delete-outline", size_hint_x=None, width=dp(36),
                    theme_icon_color="Custom", icon_color=TEXT_SECONDARY,
                    on_release=lambda x, nid=n["id"]: self._delete_note(nid),
                ))
                note_card.add_widget(nb)
                content.add_widget(note_card)
        else:
            content.add_widget(MDLabel(
                text="  暂无备注", font_style="Body", color=TEXT_SECONDARY,
                size_hint_y=None, height=dp(28),
            ))

        scroll.add_widget(content)
        root.add_widget(scroll)

    def _on_day_select(self, date_str):
        self.selected_date = date_str
        self._build()

    def _change_month(self, delta):
        self.current_month += delta
        if self.current_month > 12:
            self.current_month = 1
            self.current_year += 1
        elif self.current_month < 1:
            self.current_month = 12
            self.current_year -= 1
        self._build()

    def _refresh_after(self, card):
        Clock.schedule_once(lambda dt: self._build(), 0.3)

    # ── Swipe support ──────────────────────────────────────────

    def on_touch_down(self, touch):
        self._swipe_start_x = touch.x
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        dx = touch.x - self._swipe_start_x
        if abs(dx) > dp(60):
            self._change_month(-1 if dx > 0 else 1)
            return True
        return super().on_touch_up(touch)

    # ── Long press on calendar task ────────────────────────────

    def _calendar_task_long_press(self, card, touch):
        self._show_popup_menu([
            ("设为紧急" if card.priority != "urgent" else "设为普通",
             lambda: self._cal_toggle_priority(card)),
            ("编辑标题", lambda: self._cal_edit_task(card)),
            ("删除任务", lambda: self._cal_delete_task(card)),
        ])

    def _show_popup_menu(self, items):
        content = MDBoxLayout(orientation="vertical", spacing=dp(2),
                               padding=dp(8), size_hint_y=None,
                               height=dp(len(items) * 44 + 16))
        for label, action in items:
            btn = MDButton(
                MDButtonText(text=label),
                style="text", size_hint_y=None, height=dp(44),
                on_release=lambda x, a=action: self._dismiss_and(a),
            )
            content.add_widget(btn)
        self._popup = MDDialog(
            MDDialogContentContainer(content),
            size_hint_x=0.72, size_hint_y=None,
            height=dp(len(items) * 48 + 24),
        )
        self._popup.open()

    def _dismiss_and(self, action):
        if hasattr(self, "_popup") and self._popup:
            self._popup.dismiss()
        action()

    def _cal_toggle_priority(self, card):
        new_p = "urgent" if card.priority != "urgent" else "low"
        DB.update_task(card.task_id, priority=new_p)
        self._build()

    def _cal_edit_task(self, card):
        content = MDBoxLayout(orientation="vertical", spacing=dp(12),
                               padding=dp(12), size_hint_y=None, height=dp(100))
        tf = MDTextField(text=card.title, mode="outlined",
                          size_hint_y=None, height=dp(52))
        content.add_widget(tf)
        self._edit_dialog = MDDialog(
            MDDialogHeadlineText(text="编辑任务"),
            MDDialogContentContainer(content),
            MDDialogButtonContainer(
                MDFlatButton(text="取消",
                             on_release=lambda x: self._edit_dialog.dismiss()),
                MDRaisedButton(text="保存",
                               on_release=lambda x: self._cal_do_edit(card, tf.text.strip())),
                spacing=dp(16),
            ),
            size_hint_x=0.9,
        )
        self._edit_dialog.open()

    def _cal_do_edit(self, card, new_title):
        if not new_title:
            return
        DB.update_task(card.task_id, title=new_title)
        self._edit_dialog.dismiss()
        self._build()

    def _cal_delete_task(self, card):
        DB.delete_task(card.task_id)
        self._build()

    # ── Note operations ────────────────────────────────────────

    def _show_add_note_dialog(self):
        content = MDBoxLayout(orientation="vertical", spacing=dp(12),
                               padding=dp(12), size_hint_y=None, height=dp(130))
        tf = MDTextField(
            MDTextFieldHintText(text="备注内容"),
            mode="outlined", multiline=True,
            size_hint_y=None, height=dp(80),
        )
        content.add_widget(tf)
        self._note_dialog = MDDialog(
            MDDialogHeadlineText(text=f"添加备注 - {self.selected_date}"),
            MDDialogContentContainer(content),
            MDDialogButtonContainer(
                MDFlatButton(text="取消",
                             on_release=lambda x: self._note_dialog.dismiss()),
                MDRaisedButton(text="保存",
                               on_release=lambda x: self._do_add_note(
                                   tf.text.strip())),
                spacing=dp(16),
            ),
            size_hint_x=0.9,
        )
        self._note_dialog.open()

    def _do_add_note(self, content_text):
        if not content_text:
            return
        DB.add_note(self.selected_date, content_text)
        self._note_dialog.dismiss()
        self._build()

    def _delete_note(self, note_id):
        DB.delete_note(note_id)
        self._build()

    # ── Add task from calendar ─────────────────────────────────

    def _show_calendar_add_task_dialog(self):
        content = MDBoxLayout(orientation="vertical", spacing=dp(12),
                               padding=dp(12), size_hint_y=None, height=dp(160))
        tf = MDTextField(
            MDTextFieldHintText(text="任务标题"),
            mode="outlined", size_hint_y=None, height=dp(52),
        )
        content.add_widget(tf)

        self._cal_p = "low"
        p_row = MDBoxLayout(orientation="horizontal", spacing=dp(8),
                             size_hint_y=None, height=dp(40))
        p_row.add_widget(MDLabel(text="优先级:", size_hint_x=None, width=dp(60)))
        u_chip = MDChip(MDChipText(text="紧急"), type="choice",
                         active=False, size_hint_x=None, width=dp(60))
        l_chip = MDChip(MDChipText(text="普通"), type="choice",
                         active=True, size_hint_x=None, width=dp(60))
        u_chip.bind(on_release=lambda x: self._cal_set_p("urgent", u_chip, l_chip))
        l_chip.bind(on_release=lambda x: self._cal_set_p("low", u_chip, l_chip))
        p_row.add_widget(u_chip)
        p_row.add_widget(l_chip)
        content.add_widget(p_row)

        self._add_dialog = MDDialog(
            MDDialogHeadlineText(text=f"新建任务 - {self.selected_date}"),
            MDDialogContentContainer(content),
            MDDialogButtonContainer(
                MDFlatButton(text="取消",
                             on_release=lambda x: self._add_dialog.dismiss()),
                MDRaisedButton(text="确定",
                               on_release=lambda x: self._do_add_cal_task(
                                   tf.text.strip())),
                spacing=dp(16),
            ),
            size_hint_x=0.9,
        )
        self._add_dialog.open()

    def _cal_set_p(self, val, chip_u, chip_l):
        self._cal_p = val
        chip_u.active = (val == "urgent")
        chip_l.active = (val == "low")

    def _do_add_cal_task(self, title):
        if not title:
            return
        DB.add_task(title, priority=self._cal_p, due_date=self.selected_date)
        self._add_dialog.dismiss()
        self._build()

    def refresh(self):
        self.today = date.today()
        self.current_year  = self.today.year
        self.current_month = self.today.month
        self.selected_date = self.today.isoformat()
        self._build()


# ╔══════════════════════════════════════════════════════════════╗
# ║                     IMPORT / EXPORT                         ║
# ╚══════════════════════════════════════════════════════════════╝

class SettingsDialog:
    """Settings / Data management dialog."""

    def __init__(self, app):
        self.app = app

    def show(self):
        content = MDBoxLayout(orientation="vertical", spacing=dp(12),
                               padding=dp(12), size_hint_y=None, height=dp(180))

        export_btn = MDRaisedButton(
            MDButtonText(text="导出数据 (JSON)"),
            on_release=lambda x: self._export_data(),
        )
        content.add_widget(export_btn)

        import_btn = MDRaisedButton(
            MDButtonText(text="导入数据 (JSON)"),
            on_release=lambda x: self._show_import_dialog(),
        )
        content.add_widget(import_btn)

        info = MDLabel(
            text=f"数据文件:\n{DB._path}",
            font_style="Caption", color=TEXT_SECONDARY,
            halign="center",
        )
        content.add_widget(info)

        self._dialog = MDDialog(
            MDDialogHeadlineText(text="设置 / 数据管理"),
            MDDialogContentContainer(content),
            MDDialogButtonContainer(
                MDFlatButton(text="关闭",
                             on_release=lambda x: self._dialog.dismiss()),
                spacing=dp(16),
            ),
            size_hint_x=0.9,
        )
        self._dialog.open()

    def _export_data(self):
        try:
            json_str = DB.export_to_json()
            export_path = os.path.join(self.app.user_data_dir, "todo_export.json")
            with open(export_path, "w", encoding="utf-8") as f:
                f.write(json_str)
            if hasattr(self, "_dialog") and self._dialog:
                self._dialog.dismiss()
            MDSnackbar(
                MDSnackbarText(text=f"已导出到:\n{export_path}"),
                y=dp(24),
            ).open()
        except Exception as e:
            MDSnackbar(
                MDSnackbarText(text=f"导出失败: {e}"),
                y=dp(24),
            ).open()

    def _show_import_dialog(self):
        content = MDBoxLayout(orientation="vertical", spacing=dp(12),
                               padding=dp(12), size_hint_y=None, height=dp(200))
        content.add_widget(MDLabel(
            text="粘贴 JSON 或输入文件路径:",
            font_style="Body", color=TEXT_SECONDARY,
        ))
        tf = MDTextField(
            MDTextFieldHintText(text="粘贴 JSON 数据或输入文件路径..."),
            mode="outlined", multiline=True,
            size_hint_y=None, height=dp(120),
        )
        content.add_widget(tf)

        self._import_dialog = MDDialog(
            MDDialogHeadlineText(text="导入数据"),
            MDDialogContentContainer(content),
            MDDialogButtonContainer(
                MDFlatButton(text="取消",
                             on_release=lambda x: self._import_dialog.dismiss()),
                MDRaisedButton(text="导入",
                               on_release=lambda x: self._do_import(
                                   tf.text.strip())),
                spacing=dp(16),
            ),
            size_hint_x=0.9,
        )
        self._import_dialog.open()

    def _do_import(self, text):
        if not text:
            return
        try:
            if os.path.isfile(text):
                with open(text, "r", encoding="utf-8") as f:
                    json_str = f.read()
            else:
                json_str = text
            DB.import_from_json(json_str)
            self._import_dialog.dismiss()
            if hasattr(self, "_dialog") and self._dialog:
                self._dialog.dismiss()
            MDSnackbar(
                MDSnackbarText(text="数据导入成功！"),
                y=dp(24),
            ).open()
            self.app.refresh_all()
        except Exception as e:
            MDSnackbar(
                MDSnackbarText(text=f"导入失败: {e}"),
                y=dp(24),
            ).open()


# ╔══════════════════════════════════════════════════════════════╗
# ║                      MAIN  APPLICATION                     ║
# ╚══════════════════════════════════════════════════════════════╝

class TodoApp(MDApp):
    """Main Todo application with bottom navigation (3 tabs)."""

    def build(self):
        self.theme_cls.primary_palette = "Blue"
        self.theme_cls.theme_style     = "Light"
        self.title = "My Todo"

        DB.init(self.user_data_dir)

        # Root layout
        self.root_layout = MDBoxLayout(orientation="vertical")

        # ScreenManager for tab content
        self.sm = ScreenManager()
        self.todo_screen     = TodoScreen(app_ref=self, name="todo")
        self.project_screen  = ProjectScreen(app_ref=self, name="project")
        self.calendar_screen = CalendarScreen(app_ref=self, name="calendar")
        self.sm.add_widget(self.todo_screen)
        self.sm.add_widget(self.project_screen)
        self.sm.add_widget(self.calendar_screen)
        self.root_layout.add_widget(self.sm)

        # Bottom navigation
        self._active_idx = 0
        self._build_bottom_nav()
        self.root_layout.add_widget(self.bottom_nav)

        # Set initial tab
        self._set_active_tab(0)

        Window.bind(on_keyboard=self._on_keyboard)
        return self.root_layout

    def _build_bottom_nav(self):
        self.bottom_nav = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None, height=dp(64),
            md_bg_color=CARD_BG,
            padding=[dp(4), dp(4)],
            spacing=dp(2),
        )
        # Top border line
        with self.bottom_nav.canvas.before:
            Color(*DIVIDER_COLOR)
            self._nav_line = Line(points=[0, 0, 0, 0], width=dp(1))
        self.bottom_nav.bind(
            size=lambda inst, val: self._update_nav_line(),
            pos=lambda inst, val: self._update_nav_line(),
        )

        self._tab_widgets = []
        tabs = [
            ("急/待办", "clipboard-list", "todo"),
            ("项目",   "briefcase",      "project"),
            ("日历",   "calendar",       "calendar"),
        ]
        for label, icon, screen_name in tabs:
            tab = self._make_tab(label, icon, screen_name)
            self._tab_widgets.append(tab)
            self.bottom_nav.add_widget(tab)

        # Settings gear
        settings_btn = MDIconButton(
            icon="cog", style="standard", theme_icon_color="Custom",
            icon_color=TEXT_SECONDARY, size_hint_x=None, width=dp(48),
            on_release=lambda x: self._show_settings(),
        )
        self.bottom_nav.add_widget(settings_btn)

    def _update_nav_line(self):
        bw = self.bottom_nav
        self._nav_line.points = [bw.x, bw.y + bw.height, bw.x + bw.width, bw.y + bw.height]

    def _make_tab(self, label, icon, screen_name):
        """Create one bottom tab button."""
        box = MDBoxLayout(
            orientation="vertical", spacing=dp(0),
            size_hint_x=1, padding=[0, dp(4)],
        )
        icon_btn = MDIconButton(
            icon=icon, style="standard", theme_icon_color="Custom",
            icon_color=TEXT_SECONDARY,
            size_hint=(None, None), size=(dp(32), dp(32)),
            pos_hint={"center_x": 0.5},
        )
        lbl = MDLabel(
            text=label, font_style="Caption", color=TEXT_SECONDARY,
            halign="center", size_hint_y=None, height=dp(18),
        )
        box.add_widget(icon_btn)
        box.add_widget(lbl)

        # Make the whole box tappable via the label too
        box._icon  = icon_btn
        box._label = lbl
        box._screen = screen_name

        # Wrap in a ButtonBehavior-style touch handler
        def on_touch(b, touch):
            if b.collide_point(*touch.pos):
                self._switch_tab(screen_name)
                return True
            return False

        box.register_event_type("on_touch_down")
        base_td = box.on_touch_down
        box.on_touch_down = lambda touch: on_touch(box, touch) or base_td(touch)

        return box

    def _switch_tab(self, screen_name):
        idx = {"todo": 0, "project": 1, "calendar": 2}[screen_name]
        self._set_active_tab(idx)

    def _set_active_tab(self, idx):
        self._active_idx = idx
        names = ["todo", "project", "calendar"]
        self.sm.current = names[idx]
        for i, tw in enumerate(self._tab_widgets):
            active = (i == idx)
            c = ACCENT if active else TEXT_SECONDARY
            tw._icon.icon_color = c
            tw._label.color     = c
            tw._label.bold      = active

    def _show_settings(self):
        SettingsDialog(self).show()

    def refresh_all(self):
        self.todo_screen.refresh()
        self.project_screen.refresh()
        self.calendar_screen.refresh()

    def _on_keyboard(self, window, key, scancode, codepoint, modifier):
        if key == 27:  # Android back
            # If in project detail, go back
            if (hasattr(self.project_screen, "_detail_mode")
                    and self.project_screen._detail_mode):
                self.project_screen._go_back()
                return True
        return False


# ╔══════════════════════════════════════════════════════════════╗
# ║                       ENTRY  POINT                          ║
# ╚══════════════════════════════════════════════════════════════╝

if __name__ == "__main__":
    TodoApp().run()
