"""Computer Engineering Simulator: Main Hub prototype.

Run with ``python main.py`` after installing the approved Panda3D dependency.
Run with ``python main.py --vr`` to request the optional OpenXR runtime.
Room buttons remain disabled until their room modules are available.
"""

import math
import sys

from direct.showbase.ShowBase import ShowBase
from panda3d.core import (
    CardMaker,
    Filename,
    LineSegs,
    Point3,
    TextNode,
    TextProperties,
    TransparencyAttrib,
    WindowProperties,
)


class MainHub(ShowBase):
    def __init__(self):
        super().__init__()
        window_properties = WindowProperties()
        window_properties.setTitle("Computer Engineering Simulator")
        self.win.requestProperties(window_properties)
        thai_font_path = Filename.fromOsSpecific(r"C:\Windows\Fonts\tahoma.ttf")
        thai_font = self.loader.loadFont(str(thai_font_path))
        if thai_font is None:
            raise RuntimeError("Could not load the Windows Tahoma font for Thai text")
        self._thai_font = thai_font
        TextProperties.setDefaultFont(thai_font)
        self.setBackgroundColor(0.16, 0.12, 0.20, 1)
        self.disableMouse()
        self._mouse_look_active = False
        self._discard_mouse_sample = False
        self._heading = 0.0
        self._pitch = 0.0
        self._look_sensitivity = 0.035
        self._vr_mode = "--vr" in sys.argv
        self.openxr = None
        self._card_outlines = {}
        self._hovered_room_buttons = set()
        self._build_scene()
        self._build_ui()
        if self._vr_mode:
            self._init_vr()
        else:
            self.accept("mouse3", self._start_mouse_look)
            self.accept("mouse3-up", self._stop_mouse_look)
            self.accept("escape", self._stop_mouse_look)
        self.taskMgr.add(self._update_mouse_look, "main-hub-mouse-look")

    def _build_scene(self):
        """Build a clean, unlit room with tiled floor and a gridded ceiling."""
        self._make_card("floor", (-7, 7, -8, 14), (0, 0, 0), (0.25, 0.18, 0.22, 1), pitch=-90, outline=True)
        self._make_card("ceiling", (-7, 7, -8, 14), (0, 0, 7), (0.26, 0.22, 0.32, 1), pitch=90, outline=True)
        self._make_card(
            "back-wall", (-7, 7, -3.5, 3.5), (0, 14, 3.5), (0.62, 0.50, 0.66, 1), outline=True
        )
        self._make_card(
            "left-wall", (-8, 14, -3.5, 3.5), (-7, 0, 3.5), (0.52, 0.45, 0.62, 1), heading=90, outline=True
        )
        self._make_card(
            "right-wall", (-8, 14, -3.5, 3.5), (7, 0, 3.5), (0.52, 0.45, 0.62, 1), heading=-90, outline=True
        )
        self._build_room_grid()
        self._build_furniture()
        self._build_neon_decor()

        # Start at the room center. Desktop look is a separate transform so an
        # XR runtime can supply head pose without sharing mouse rotation.
        self.camera_rig = self.render.attachNewNode("camera-rig")
        # Desktop starts at seated eye height. OpenXR supplies the real HMD pose.
        self.camera_rig.setPos(0, 3, 1.18)
        self.desktop_look = self.camera_rig.attachNewNode("desktop-look")
        self.camera.reparentTo(self.desktop_look)
        self.camera.setPos(0, 0, 0)
        self.camera.setHpr(0, 0, 0)
        self.camLens.setFov(65)

    def _make_card(self, name, frame, position, color, heading=0, pitch=0, roll=0, outline=False):
        maker = CardMaker(name)
        maker.setFrame(*frame)
        card = self.render.attachNewNode(maker.generate())
        card.setPos(*position)
        card.setH(heading)
        card.setP(pitch)
        card.setR(roll)
        card.setColor(*color)
        card.setLightOff(1)
        card.setTwoSided(True)
        if outline:
            self._card_outlines[name] = self._make_rectangle_outline(card, frame)
        return card

    def _make_rectangle_outline(self, parent, frame, color=(0.015, 0.018, 0.03, 1), thickness=2.0, offset=-0.004):
        left, right, bottom, top = frame
        line = LineSegs("black-outline")
        line.setThickness(thickness)
        line.setColor(*color)
        corners = ((left, offset, bottom), (right, offset, bottom),
                   (right, offset, top), (left, offset, top))
        for index in range(4):
            line.moveTo(*corners[index])
            line.drawTo(*corners[(index + 1) % 4])
        outline = parent.attachNewNode(line.create())
        outline.setLightOff(1)
        return outline

    def _make_box(self, name, center, size, color):
        """Create a flat-shaded cuboid from six CardMaker faces."""
        width, depth, height = size
        root = self.render.attachNewNode(name)
        faces = [
            ((-width / 2, width / 2, -height / 2, height / 2), (0, -depth / 2, 0), 0, 0),
            ((-width / 2, width / 2, -height / 2, height / 2), (0, depth / 2, 0), 180, 0),
            ((-depth / 2, depth / 2, -height / 2, height / 2), (-width / 2, 0, 0), 90, 0),
            ((-depth / 2, depth / 2, -height / 2, height / 2), (width / 2, 0, 0), -90, 0),
            ((-width / 2, width / 2, -depth / 2, depth / 2), (0, 0, height / 2), 0, -90),
            ((-width / 2, width / 2, -depth / 2, depth / 2), (0, 0, -height / 2), 0, 90),
        ]
        for index, (frame, offset, heading, pitch) in enumerate(faces):
            maker = CardMaker(f"{name}-face-{index}")
            maker.setFrame(*frame)
            face = root.attachNewNode(maker.generate())
            face.setPos(*offset)
            face.setHpr(heading, pitch, 0)
            face.setColor(*color)
            face.setLightOff(1)
            face.setTwoSided(True)
        edge_x = width / 2 + 0.002
        edge_y = depth / 2 + 0.002
        edge_z = height / 2 + 0.002
        corners = [
            (x * edge_x, y * edge_y, z * edge_z)
            for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)
        ]
        edges = LineSegs(f"{name}-black-edges")
        edges.setThickness(1.6)
        edges.setColor(0.012, 0.014, 0.022, 1)
        for first in range(8):
            for second in range(first + 1, 8):
                if sum(a != b for a, b in zip(corners[first], corners[second])) == 1:
                    edges.moveTo(*corners[first])
                    edges.drawTo(*corners[second])
        root.attachNewNode(edges.create()).setLightOff(1)
        root.setPos(*center)
        return root

    def _build_furniture(self):
        """Add a bare computer desk and a simple white molded chair."""
        desk_y = 5.5
        wood = (0.30, 0.32, 0.34, 1)
        frame = (0.20, 0.22, 0.24, 1)
        # Keep the desk top bare, as requested.
        self._make_box("desk-top", (0, desk_y, 0.76), (2.4, 0.90, 0.12), wood)
        for x in (-1.0, 1.0):
            for y in (desk_y - 0.32, desk_y + 0.32):
                self._make_box("desk-leg", (x, y, 0.36), (0.12, 0.12, 0.72), frame)
        self._make_box("desk-support", (0, desk_y, 0.29), (2.0, 0.10, 0.10), frame)

        chair_y = 3.0
        plastic = (0.90, 0.91, 0.91, 1)
        self._make_box("chair-seat", (0, chair_y, 0.64), (0.72, 0.70, 0.11), plastic)
        self._make_box("chair-back", (0, chair_y - 0.31, 1.08), (0.72, 0.10, 0.82), plastic)
        for x in (-0.22, -0.11, 0, 0.11, 0.22):
            self._make_box("chair-back-slat", (x, chair_y - 0.365, 1.10), (0.035, 0.012, 0.55), (0.78, 0.80, 0.80, 1))
        for x in (-0.45, 0.45):
            self._make_box("chair-arm", (x, chair_y + 0.02, 0.92), (0.09, 0.62, 0.09), plastic)
            self._make_box("chair-arm-support", (x, chair_y + 0.23, 0.78), (0.07, 0.08, 0.30), plastic)
            self._make_box("chair-front-leg", (x * 0.85, chair_y + 0.22, 0.32), (0.08, 0.08, 0.64), plastic)
            self._make_box("chair-rear-leg", (x * 0.85, chair_y - 0.22, 0.32), (0.08, 0.08, 0.64), plastic)

        # Monitor, sound bar, keyboard, mouse and illuminated desk mat.
        self._make_box("monitor-frame", (0, 5.76, 1.13), (1.08, 0.10, 0.52), (0.10, 0.11, 0.16, 1))
        self._make_card("monitor-screen", (-0.49, 0.49, -0.225, 0.225), (0, 5.704, 1.13), (0.07, 0.14, 0.23, 1), outline=True)
        screen_art = LineSegs("monitor-wallpaper-lines")
        screen_art.setThickness(2)
        screen_art.setColor(0.10, 0.76, 1.0, 1)
        screen_art.moveTo(-0.43, 5.696, 0.99)
        screen_art.drawTo(-0.20, 5.696, 1.18)
        screen_art.drawTo(0.02, 5.696, 1.08)
        screen_art.drawTo(0.22, 5.696, 1.29)
        screen_art.drawTo(0.43, 5.696, 1.19)
        screen_art.moveTo(-0.42, 5.696, 1.34)
        screen_art.drawTo(0.42, 5.696, 1.34)
        self.render.attachNewNode(screen_art.create()).setLightOff(1)
        screen_accent = LineSegs("monitor-wallpaper-accent")
        screen_accent.setThickness(2)
        screen_accent.setColor(0.92, 0.24, 0.82, 1)
        screen_accent.moveTo(-0.40, 5.695, 1.02)
        screen_accent.drawTo(-0.16, 5.695, 1.20)
        screen_accent.drawTo(0.05, 5.695, 1.11)
        screen_accent.drawTo(0.26, 5.695, 1.30)
        self.render.attachNewNode(screen_accent.create()).setLightOff(1)
        self._make_box("monitor-stand", (0, 5.80, 0.92), (0.11, 0.12, 0.28), frame)
        self._make_box("monitor-foot", (0, 5.72, 0.855), (0.40, 0.25, 0.035), frame)
        self._make_box("monitor-light-bar", (0, 5.70, 1.43), (0.86, 0.05, 0.035), (0.54, 0.46, 0.62, 1))

        mat_center = (0, 5.30, 0.835)
        self._make_box("desk-mat", mat_center, (1.60, 0.48, 0.025), (0.08, 0.11, 0.18, 1))
        for x in (-0.81, 0.81):
            self._make_box("mat-neon-side", (x, 5.30, 0.851), (0.025, 0.50, 0.018), (0.10, 0.84, 1.0, 1))
        for y in (5.05, 5.55):
            self._make_box("mat-neon-edge", (0, y, 0.851), (1.62, 0.025, 0.018), (0.10, 0.84, 1.0, 1))
        self._make_box("keyboard", (-0.18, 5.31, 0.875), (0.92, 0.29, 0.055), (0.16, 0.18, 0.24, 1))
        for row in range(3):
            for column in range(11):
                key_x = -0.60 + column * 0.084
                key_y = 5.215 + row * 0.083
                color = ((0.15, 0.82, 0.96, 1) if (column + row) % 3 == 0 else (0.69, 0.34, 0.91, 1))
                self._make_box("keyboard-key", (key_x, key_y, 0.908), (0.060, 0.050, 0.012), color)
        self._make_box("mouse", (0.73, 5.30, 0.875), (0.20, 0.29, 0.075), (0.70, 0.74, 0.79, 1))
        self._make_box("mouse-wheel", (0.73, 5.29, 0.916), (0.025, 0.07, 0.012), (0.10, 0.84, 1.0, 1))

        # A compact tower sits just outside the desk's right edge so it remains visible.
        self._make_box("pc-case", (1.45, 5.48, 0.38), (0.38, 0.58, 0.72), (0.10, 0.11, 0.16, 1))
        self._make_card("pc-front", (-0.15, 0.15, -0.31, 0.31), (1.45, 5.176, 0.38), (0.055, 0.065, 0.095, 1), outline=True)
        self._make_box("pc-rgb-blue", (1.37, 5.165, 0.38), (0.028, 0.018, 0.54), (0.05, 0.70, 1.0, 1))
        self._make_box("pc-rgb-pink", (1.46, 5.165, 0.38), (0.028, 0.018, 0.54), (1.0, 0.12, 0.62, 1))

        # A simple headphone set resting beside the mouse.
        self._make_box("headphone-left-ear", (0.93, 5.70, 0.99), (0.13, 0.12, 0.25), (0.12, 0.14, 0.20, 1))
        self._make_box("headphone-right-ear", (1.23, 5.70, 0.99), (0.13, 0.12, 0.25), (0.12, 0.14, 0.20, 1))
        band = LineSegs("headphone-band")
        band.setThickness(4)
        band.setColor(0.12, 0.84, 1.0, 1)
        for step in range(13):
            angle_a = (step / 12) * math.pi
            angle_b = ((step + 1) / 12) * math.pi
            a = (1.08 + 0.15 * math.cos(angle_a), 5.70, 1.03 + 0.27 * math.sin(angle_a))
            b = (1.08 + 0.15 * math.cos(angle_b), 5.70, 1.03 + 0.27 * math.sin(angle_b))
            band.moveTo(*a)
            band.drawTo(*b)
        self.render.attachNewNode(band.create()).setLightOff(1)

        self._build_shelf()

    def _build_shelf(self):
        shelf_x, shelf_y = -4.20, 8.2
        shelf_white = (0.83, 0.82, 0.91, 1)
        for x in (shelf_x - 0.52, shelf_x + 0.52):
            self._make_box("shelf-upright", (x, shelf_y, 1.15), (0.07, 0.08, 2.30), shelf_white)
        for level in (0.50, 1.22, 1.94):
            self._make_box("shelf-board", (shelf_x, shelf_y, level), (1.18, 0.42, 0.07), shelf_white)
        # Small shelf props from the reference: a game case, controller and figure.
        self._make_box("game-case", (shelf_x + 0.28, shelf_y - 0.14, 1.56), (0.26, 0.08, 0.34), (0.14, 0.23, 0.48, 1))
        self._make_box("controller", (shelf_x - 0.18, shelf_y - 0.15, 2.08), (0.40, 0.16, 0.12), (0.77, 0.78, 0.86, 1))
        self._make_box("toy-figure-body", (shelf_x - 0.27, shelf_y - 0.15, 0.83), (0.24, 0.20, 0.34), (0.96, 0.32, 0.12, 1))
        self._make_box("toy-figure-head", (shelf_x - 0.27, shelf_y - 0.15, 1.06), (0.19, 0.18, 0.14), (1.0, 0.43, 0.16, 1))

    def _build_neon_decor(self):
        # Hexagonal wall lights and cyan/pink ambient strips, kept unlit and flat.
        lights = LineSegs("hexagon-wall-lights")
        lights.setThickness(4)
        lights.setColor(1.0, 0.28, 0.88, 1)
        for center_x, center_z in ((-4.2, 5.7), (-3.2, 5.7), (3.2, 5.7), (4.2, 5.7), (5.2, 4.8)):
            points = []
            for side in range(6):
                angle = side * math.pi / 3
                points.append((center_x + 0.48 * math.cos(angle), 13.96,
                               center_z + 0.48 * math.sin(angle)))
            for side in range(6):
                lights.moveTo(*points[side])
                lights.drawTo(*points[(side + 1) % 6])
        self.render.attachNewNode(lights.create()).setLightOff(1)

        strip = LineSegs("wall-led-strip")
        strip.setThickness(5)
        strip.setColor(0.08, 0.78, 1.0, 1)
        strip.moveTo(-6.8, 13.96, 0.20)
        strip.drawTo(6.8, 13.96, 0.20)
        self.render.attachNewNode(strip.create()).setLightOff(1)

    def _build_room_grid(self):
        floor_lines = LineSegs("floor-tiles")
        floor_lines.setThickness(1.2)
        floor_lines.setColor(0.38, 0.29, 0.34, 1)
        for x in range(-7, 8, 1):
            floor_lines.moveTo(x, -8, 0.006)
            floor_lines.drawTo(x, 14, 0.006)
        for y in range(-8, 15, 2):
            floor_lines.moveTo(-7, y, 0.006)
            floor_lines.drawTo(7, y, 0.006)
        self.render.attachNewNode(floor_lines.create()).setLightOff(1)

        ceiling_lines = LineSegs("ceiling-panels")
        ceiling_lines.setThickness(2.0)
        ceiling_lines.setColor(0.42, 0.34, 0.49, 1)
        for x in range(-6, 7, 2):
            ceiling_lines.moveTo(x, -8, 6.994)
            ceiling_lines.drawTo(x, 14, 6.994)
        for y in range(-8, 15, 2):
            ceiling_lines.moveTo(-7, y, 6.994)
            ceiling_lines.drawTo(7, y, 6.994)
        self.render.attachNewNode(ceiling_lines.create()).setLightOff(1)

        wall_lines = LineSegs("wall-panels")
        wall_lines.setThickness(1.0)
        wall_lines.setColor(0.72, 0.61, 0.76, 1)
        for x in range(-6, 7, 2):
            wall_lines.moveTo(x, 13.994, 0)
            wall_lines.drawTo(x, 13.994, 7)
        for z in (1.5, 3.0, 4.5, 6.0):
            wall_lines.moveTo(-7, 13.994, z)
            wall_lines.drawTo(7, 13.994, z)
        for y in range(-8, 15, 2):
            wall_lines.moveTo(-6.994, y, 0)
            wall_lines.drawTo(-6.994, y, 7)
            wall_lines.moveTo(6.994, y, 0)
            wall_lines.drawTo(6.994, y, 7)
        for z in (1.5, 3.0, 4.5, 6.0):
            wall_lines.moveTo(-6.994, -8, z)
            wall_lines.drawTo(-6.994, 14, z)
            wall_lines.moveTo(6.994, -8, z)
            wall_lines.drawTo(6.994, 14, z)
        self.render.attachNewNode(wall_lines.create()).setLightOff(1)

    def _start_mouse_look(self):
        self._mouse_look_active = True
        properties = WindowProperties()
        # Re-centering is used instead of M_confined because Windows may not
        # support that mode on every display driver.
        properties.setMouseMode(WindowProperties.M_absolute)
        properties.setCursorHidden(True)
        self.win.requestProperties(properties)
        self._center_mouse()
        self._discard_mouse_sample = True

    def _stop_mouse_look(self):
        if not self._mouse_look_active:
            return
        self._mouse_look_active = False
        properties = WindowProperties()
        properties.setMouseMode(WindowProperties.M_absolute)
        properties.setCursorHidden(False)
        self.win.requestProperties(properties)

    def _center_mouse(self):
        properties = self.win.getProperties()
        self.win.movePointer(0, properties.getXSize() // 2, properties.getYSize() // 2)

    def _update_mouse_look(self, task):
        if not self._mouse_look_active or not self.mouseWatcherNode.hasMouse():
            return task.cont

        if self._discard_mouse_sample:
            self._discard_mouse_sample = False
            self._center_mouse()
            return task.cont

        mouse_x = self.mouseWatcherNode.getMouseX()
        mouse_y = self.mouseWatcherNode.getMouseY()
        self._heading -= mouse_x * self._look_sensitivity * 100
        self._pitch = max(-80, min(80, self._pitch + mouse_y * self._look_sensitivity * 100))
        self.desktop_look.setH(self._heading)
        self.desktop_look.setP(self._pitch)
        self._center_mouse()
        return task.cont

    def _build_ui(self):
        # Separate world-space panels remain readable from the seated desk view
        # on desktop and from stereo XR cameras.
        self.ui_board = self.render.attachNewNode("hub-ui-board")
        self.ui_board.setPos(0, 7.95, 0)
        self.room_buttons = []
        self._make_world_text("เครื่องจำลองวิศวกรรมคอมพิวเตอร์", (0, 7.91, 3.34), 0.16, (0.95, 0.91, 1.0, 1))
        self._make_world_text("ห้องหลัก", (0, 7.91, 3.14), 0.105, (0.30, 0.84, 1.0, 1))

        cards = [
            ("PC Assembly", "เลือกและประกอบ\nชิ้นส่วนคอมพิวเตอร์"),
            ("Networking", "เรียนรู้สาย LAN มาตรฐาน T568B\nและจำลองการเชื่อมต่อ"),
            ("Programming", "ฝึกตรรกะ เติมโค้ด และทำภารกิจ\nจำลองสำหรับหุ่นยนต์"),
        ]
        centers_x = (-1.95, 0.0, 1.95)
        for index, (title, description) in enumerate(cards):
            x = centers_x[index]
            z = 2.28
            self._make_card(
                f"room-panel-{index}", (-0.88, 0.88, -0.68, 0.68),
                (x, 7.94, z), (0.83, 0.81, 0.89, 1), outline=True
            )
            self._make_world_text(title, (x, 7.91, z + 0.40), 0.105, (0.15, 0.13, 0.20, 1))
            self._make_world_text(description, (x, 7.91, z + 0.12), 0.08, (0.23, 0.20, 0.29, 1))
            button_card = self._make_card(
                f"room-button-{index}", (-0.60, 0.60, -0.15, 0.15),
                (x, 7.91, z - 0.42), (0.56, 0.53, 0.63, 1), outline=True
            )
            glow_soft = self._make_rectangle_outline(
                button_card, (-0.63, 0.63, -0.18, 0.18),
                color=(1, 1, 1, 0.35), thickness=6.0, offset=-0.018,
            )
            glow_soft.setTransparency(TransparencyAttrib.M_alpha)
            glow_soft.setColor(1, 1, 1, 0.35, 10)
            glow_core = self._make_rectangle_outline(
                button_card, (-0.60, 0.60, -0.15, 0.15),
                color=(1, 1, 1, 1), thickness=2.5, offset=-0.022,
            )
            glow_core.setColor(1, 1, 1, 1, 10)
            glow_soft.stash()
            glow_core.stash()
            self._make_world_text("ยังไม่พร้อม", (x, 7.88, z - 0.46), 0.065, (0.91, 0.88, 0.95, 1))
            self.room_buttons.append({
                "bounds": (x - 0.60, x + 0.60),
                "center_z": z - 0.42,
                "state": "disabled",
                "callback": None,
                "black_outline": self._card_outlines[f"room-button-{index}"],
                "glow": (glow_soft, glow_core),
            })


    def _make_world_text(self, text, position, scale, color, align=TextNode.ACenter):
        node = TextNode("hub-text")
        node.setFont(self._thai_font)
        node.setText(text)
        node.setAlign(align)
        node.setTextColor(*color)
        path = self.render.attachNewNode(node)
        path.setPos(*position)
        path.setScale(scale)
        path.setTwoSided(True)
        return path

    def _init_vr(self):
        try:
            from vr_support import initialize_openxr

            self.openxr = initialize_openxr(self)
        except Exception as exc:
            raise RuntimeError(
                "OpenXR could not start. Connect the headset and make its OpenXR "
                "runtime active in Meta Quest Link, SteamVR, or the headset vendor's "
                f"runtime, then run with --vr again. Details: {exc}"
            ) from exc

        # Stage space starts at the room entrance; the tracked HMD supplies eye height.
        self.openxr.tracking_space_anchor.setPos(0, 3, 0)
        self.taskMgr.add(self._update_vr_select, "main-hub-vr-select", sort=1)

    def _update_vr_select(self, task):
        actions = self.openxr.action_set
        hovered = set()
        for hand in ("left", "right"):
            target_index = self._pointed_room_button(hand)
            if target_index is None:
                continue
            hovered.add(target_index)
            if actions.select_just_pressed[hand]:
                target = self.room_buttons[target_index]
                if target["state"] != "disabled" and target["callback"] is not None:
                    target["callback"]()
        self._set_hovered_room_buttons(hovered)
        return task.cont

    def _pointed_room_button(self, hand):
        anchor = self.openxr.left_hand_anchor if hand == "left" else self.openxr.right_hand_anchor
        if anchor.isStashed():
            return None

        origin = anchor.getPos(self.render)
        direction = anchor.getQuat(self.render).getForward()
        if abs(direction.y) < 1e-5:
            return None
        distance = (self.ui_board.getY(self.render) - origin.y) / direction.y
        if distance <= 0:
            return None

        world_hit = Point3(origin + direction * distance)
        board_hit = self.ui_board.getRelativePoint(self.render, world_hit)
        for index, button in enumerate(self.room_buttons):
            left, right = button["bounds"]
            center_z = button["center_z"]
            if left <= board_hit.x <= right and center_z - 0.15 <= board_hit.z <= center_z + 0.15:
                return index
        return None

    def _set_hovered_room_buttons(self, hovered):
        hovered = set(hovered)
        for index, button in enumerate(self.room_buttons):
            is_hovered = index in hovered
            was_hovered = index in self._hovered_room_buttons
            if is_hovered == was_hovered:
                continue
            if is_hovered:
                button["black_outline"].stash()
                for glow in button["glow"]:
                    glow.unstash()
            else:
                button["black_outline"].unstash()
                for glow in button["glow"]:
                    glow.stash()
        self._hovered_room_buttons = hovered


if __name__ == "__main__":
    MainHub().run()
