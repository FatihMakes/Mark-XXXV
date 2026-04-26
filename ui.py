import os, json, time, math, random, threading
import tkinter as tk
from collections import deque
from PIL import Image, ImageTk, ImageDraw
import sys
from pathlib import Path


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR   = get_base_dir()
CONFIG_DIR = BASE_DIR / "config"
API_FILE   = CONFIG_DIR / "api_keys.json"

SYSTEM_NAME = "J.A.R.V.I.S"
MODEL_BADGE = "MARK XXXV"

C_BG     = "#000000"
C_PRI    = "#00d4ff"
C_MID    = "#007a99"
C_DIM    = "#003344"
C_DIMMER = "#001520"
C_ACC    = "#ff6600"
C_ACC2   = "#ffcc00"
C_TEXT   = "#8ffcff"
C_PANEL  = "#010c10"
C_GREEN  = "#00ff88"
C_RED    = "#ff3333"
C_MUTED  = "#ff3366"


class JarvisUI:
    def __init__(self, face_path, size=None):
        self.root = tk.Tk()
        self.root.title("J.A.R.V.I.S — MARK XXXV")
        self.root.resizable(False, False)

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        W  = min(sw, 984)
        H  = min(sh, 816)
        self.root.geometry(f"{W}x{H}+{(sw-W)//2}+{(sh-H)//2}")
        self.root.configure(bg=C_BG)

        self.W = W
        self.H = H

        self.FACE_SZ = min(int(H * 0.54), 400)
        self.FCX     = W // 2
        self.FCY     = int(H * 0.13) + self.FACE_SZ // 2

        # ── Durum ────────────────────────────────────────────────────────────
        self.speaking     = False
        self.muted        = False          # Mute flag — main.py okur
        self.scale        = 1.0
        self.target_scale = 1.0
        self.halo_a       = 60.0
        self.target_halo  = 60.0
        self.last_t       = time.time()
        self.tick         = 0
        self.scan_angle   = 0.0
        self.scan2_angle  = 180.0
        self.rings_spin   = [0.0, 120.0, 240.0]
        self.pulse_r      = [0.0, self.FACE_SZ * 0.26, self.FACE_SZ * 0.52]
        self.status_text  = "INITIALISING"
        self.status_blink = True

        # Dışarıdan set edilebilen durum (main.py çağırır)
        # Değerler: "LISTENING" | "SPEAKING" | "THINKING" | "MUTED" | "ONLINE"
        self._jarvis_state = "INITIALISING"

        self.typing_queue = deque()
        self.is_typing    = False

        # Klavye girişinden komutu iletmek için callback — main.py atar
        self.on_text_command = None

        self._face_pil         = None
        self._has_face         = False
        self._face_scale_cache = None
        self._load_face(face_path)

        # ── Canvas (arka plan animasyon) ─────────────────────────────────────
        self.bg = tk.Canvas(self.root, width=W, height=H,
                            bg=C_BG, highlightthickness=0)
        self.bg.place(x=0, y=0)

        # ── Log alanı ────────────────────────────────────────────────────────
        LW = int(W * 0.72)
        LH = 110
        LOG_Y = H - LH - 80   # klavye inputu için yukarı çektik
        self.log_frame = tk.Frame(self.root, bg=C_PANEL,
                                  highlightbackground=C_MID,
                                  highlightthickness=1)
        self.log_frame.place(x=(W - LW) // 2, y=LOG_Y, width=LW, height=LH)
        self.log_text = tk.Text(self.log_frame, fg=C_TEXT, bg=C_PANEL,
                                insertbackground=C_TEXT, borderwidth=0,
                                wrap="word", font=("Courier", 10), padx=10, pady=6)
        self.log_text.pack(fill="both", expand=True)
        self.log_text.configure(state="disabled")
        self.log_text.tag_config("you", foreground="#e8e8e8")
        self.log_text.tag_config("ai",  foreground=C_PRI)
        self.log_text.tag_config("sys", foreground=C_ACC2)
        self.log_text.tag_config("err", foreground=C_RED)

        # ── Klavye girişi ─────────────────────────────────────────────────────
        INPUT_Y = LOG_Y + LH + 6
        self._build_input_bar(LW, INPUT_Y)

        # ── Mute butonu ───────────────────────────────────────────────────────
        self._build_mute_button()

        # ── F4 kısayolu ───────────────────────────────────────────────────────
        self.root.bind("<F4>", lambda e: self._toggle_mute())

        # ── API key ───────────────────────────────────────────────────────────
        self._api_key_ready = self._api_keys_exist()
        if not self._api_key_ready:
            self._show_setup_ui()

        self._animate()
        self.root.protocol("WM_DELETE_WINDOW", lambda: os._exit(0))
        self.overlay = JarvisOverlay(self.root)

    # ── Mute butonu ───────────────────────────────────────────────────────────

    def _build_mute_button(self):
        """Sol alt köşeye mute butonu yerleştirir."""
        BTN_W, BTN_H = 110, 32
        BTN_X = 18
        BTN_Y = self.H - 70

        self._mute_canvas = tk.Canvas(
            self.root, width=BTN_W, height=BTN_H,
            bg=C_BG, highlightthickness=0, cursor="hand2"
        )
        self._mute_canvas.place(x=BTN_X, y=BTN_Y)
        self._mute_canvas.bind("<Button-1>", lambda e: self._toggle_mute())
        self._draw_mute_button()

    def _draw_mute_button(self):
        c = self._mute_canvas
        c.delete("all")
        if self.muted:
            border = C_MUTED
            fill   = "#1a0008"
            icon   = "🔇"
            label  = " MUTED"
            fg     = C_MUTED
        else:
            border = C_MID
            fill   = C_PANEL
            icon   = "🎙"
            label  = " LIVE"
            fg     = C_GREEN

        c.create_rectangle(0, 0, 110, 32, outline=border, fill=fill, width=1)
        c.create_text(55, 16, text=f"{icon}{label}",
                      fill=fg, font=("Courier", 10, "bold"))

    def _toggle_mute(self):
        self.muted = not self.muted
        self._draw_mute_button()
        if self.muted:
            self.set_state("MUTED")
            self.write_log("SYS: Microphone muted.")
        else:
            self.set_state("LISTENING")
            self.write_log("SYS: Microphone active.")

    # ── Klavye girişi ─────────────────────────────────────────────────────────

    def _build_input_bar(self, lw: int, y: int):
        """Log'un hemen altına tek satır metin giriş alanı."""
        x0    = (self.W - lw) // 2
        BTN_W = 70
        INP_W = lw - BTN_W - 4

        self._input_var = tk.StringVar()

        self._input_entry = tk.Entry(
            self.root,
            textvariable=self._input_var,
            fg=C_TEXT, bg="#000d12",
            insertbackground=C_TEXT,
            borderwidth=0,
            font=("Courier", 10),
            highlightthickness=1,
            highlightbackground=C_DIM,
            highlightcolor=C_PRI,
        )
        self._input_entry.place(x=x0, y=y, width=INP_W, height=28)
        self._input_entry.bind("<Return>", self._on_input_submit)
        self._input_entry.bind("<KP_Enter>", self._on_input_submit)

        self._send_btn = tk.Button(
            self.root,
            text="SEND ▸",
            command=self._on_input_submit,
            fg=C_PRI, bg=C_PANEL,
            activeforeground=C_BG, activebackground=C_PRI,
            font=("Courier", 9, "bold"),
            borderwidth=0, cursor="hand2",
            highlightthickness=1,
            highlightbackground=C_MID,
        )
        self._send_btn.place(x=x0 + INP_W + 4, y=y, width=BTN_W, height=28)

    def _on_input_submit(self, event=None):
        text = self._input_var.get().strip()
        if not text:
            return
        self._input_var.set("")
        self.write_log(f"You: {text}")
        if self.on_text_command:
            threading.Thread(
                target=self.on_text_command,
                args=(text,),
                daemon=True
            ).start()

    # ── Durum yönetimi ────────────────────────────────────────────────────────

    def set_state(self, state: str):
        """
        main.py'den çağrılır.
        state: LISTENING | SPEAKING | THINKING | MUTED | ONLINE | PROCESSING
        """
        self._jarvis_state = state
        if state == "MUTED":
            self.status_text = "MUTED"
            self.speaking    = False
        elif state == "SPEAKING":
            self.status_text = "SPEAKING"
            self.speaking    = True
        elif state == "THINKING":
            self.status_text = "THINKING"
            self.speaking    = False
        elif state == "LISTENING":
            self.status_text = "LISTENING"
            self.speaking    = False
        elif state == "PROCESSING":
            self.status_text = "PROCESSING"
            self.speaking    = False
        else:
            self.status_text = "ONLINE"
            self.speaking    = False

    # ── Yüz yükleme ───────────────────────────────────────────────────────────

    def _load_face(self, path):
        FW = self.FACE_SZ
        try:
            img  = Image.open(path).convert("RGBA").resize((FW, FW), Image.LANCZOS)
            mask = Image.new("L", (FW, FW), 0)
            ImageDraw.Draw(mask).ellipse((2, 2, FW - 2, FW - 2), fill=255)
            img.putalpha(mask)
            self._face_pil = img
            self._has_face = True
        except Exception:
            self._has_face = False

    @staticmethod
    def _ac(r, g, b, a):
        f = a / 255.0
        return f"#{int(r*f):02x}{int(g*f):02x}{int(b*f):02x}"

    # ── Animasyon döngüsü ─────────────────────────────────────────────────────

    def _animate(self):
        self.tick += 1
        t   = self.tick
        now = time.time()

        if now - self.last_t > (0.14 if self.speaking else 0.55):
            if self.speaking:
                self.target_scale = random.uniform(1.05, 1.11)
                self.target_halo  = random.uniform(138, 182)
            elif self.muted:
                self.target_scale = random.uniform(0.998, 1.001)
                self.target_halo  = random.uniform(20, 32)
            else:
                self.target_scale = random.uniform(1.001, 1.007)
                self.target_halo  = random.uniform(50, 68)
            self.last_t = now

        sp = 0.35 if self.speaking else 0.16
        self.scale  += (self.target_scale - self.scale) * sp
        self.halo_a += (self.target_halo  - self.halo_a) * sp

        for i, spd in enumerate([1.2, -0.8, 1.9] if self.speaking else [0.5, -0.3, 0.82]):
            self.rings_spin[i] = (self.rings_spin[i] + spd) % 360

        self.scan_angle  = (self.scan_angle  + (2.8 if self.speaking else 1.2)) % 360
        self.scan2_angle = (self.scan2_angle + (-1.7 if self.speaking else -0.68)) % 360

        pspd  = 3.8 if self.speaking else 1.8
        limit = self.FACE_SZ * 0.72
        new_p = [r + pspd for r in self.pulse_r if r + pspd < limit]
        if len(new_p) < 3 and random.random() < (0.06 if self.speaking else 0.022):
            new_p.append(0.0)
        self.pulse_r = new_p

        if t % 40 == 0:
            self.status_blink = not self.status_blink

        self._draw()
        self.root.after(16, self._animate)

    # ── Çizim ─────────────────────────────────────────────────────────────────

    def _draw(self):
        c    = self.bg
        W, H = self.W, self.H
        t    = self.tick
        FCX  = self.FCX
        FCY  = self.FCY
        FW   = self.FACE_SZ
        c.delete("all")

        # Arka plan grid
        for x in range(0, W, 44):
            for y in range(0, H, 44):
                c.create_rectangle(x, y, x+1, y+1, fill=C_DIMMER, outline="")

        # Halo halkaları
        for r in range(int(FW * 0.54), int(FW * 0.28), -22):
            frac = 1.0 - (r - FW * 0.28) / (FW * 0.26)
            ga   = max(0, min(255, int(self.halo_a * 0.09 * frac)))
            # Mute modda kırmızı halo
            if self.muted:
                gh = f"{ga:02x}"
                c.create_oval(FCX-r, FCY-r, FCX+r, FCY+r,
                              outline=f"#{gh}0011", width=2)
            else:
                gh = f"{ga:02x}"
                c.create_oval(FCX-r, FCY-r, FCX+r, FCY+r,
                              outline=f"#00{gh}ff", width=2)

        # Pulse dalgaları
        for pr in self.pulse_r:
            pa = max(0, int(220 * (1.0 - pr / (FW * 0.72))))
            r  = int(pr)
            if self.muted:
                c.create_oval(FCX-r, FCY-r, FCX+r, FCY+r,
                              outline=self._ac(255, 30, 80, pa // 3), width=2)
            else:
                c.create_oval(FCX-r, FCY-r, FCX+r, FCY+r,
                              outline=self._ac(0, 212, 255, pa), width=2)

        # Dönen halkalar
        for idx, (r_frac, w_ring, arc_l, gap) in enumerate([
                (0.47, 3, 110, 75), (0.39, 2, 75, 55), (0.31, 1, 55, 38)]):
            ring_r = int(FW * r_frac)
            base_a = self.rings_spin[idx]
            a_val  = max(0, min(255, int(self.halo_a * (1.0 - idx * 0.18))))
            col    = self._ac(255, 30, 80, a_val) if self.muted else self._ac(0, 212, 255, a_val)
            for s in range(360 // (arc_l + gap)):
                start = (base_a + s * (arc_l + gap)) % 360
                c.create_arc(FCX-ring_r, FCY-ring_r, FCX+ring_r, FCY+ring_r,
                             start=start, extent=arc_l,
                             outline=col, width=w_ring, style="arc")

        # Tarama yayları
        sr      = int(FW * 0.49)
        scan_a  = min(255, int(self.halo_a * 1.4))
        arc_ext = 70 if self.speaking else 42
        scan_col = self._ac(255, 30, 80, scan_a) if self.muted else self._ac(0, 212, 255, scan_a)
        c.create_arc(FCX-sr, FCY-sr, FCX+sr, FCY+sr,
                     start=self.scan_angle, extent=arc_ext,
                     outline=scan_col, width=3, style="arc")
        c.create_arc(FCX-sr, FCY-sr, FCX+sr, FCY+sr,
                     start=self.scan2_angle, extent=arc_ext,
                     outline=self._ac(255, 100, 0, scan_a // 2), width=2, style="arc")

        # Derecelendirme işaretleri
        t_out = int(FW * 0.495)
        t_in  = int(FW * 0.472)
        a_mk  = self._ac(0, 212, 255, 155)
        for deg in range(0, 360, 10):
            rad = math.radians(deg)
            inn = t_in if deg % 30 == 0 else t_in + 5
            c.create_line(FCX + t_out * math.cos(rad), FCY - t_out * math.sin(rad),
                          FCX + inn  * math.cos(rad), FCY - inn  * math.sin(rad),
                          fill=a_mk, width=1)

        # Crosshair
        ch_r = int(FW * 0.50)
        gap  = int(FW * 0.15)
        ch_a = self._ac(0, 212, 255, int(self.halo_a * 0.55))
        for x1, y1, x2, y2 in [
                (FCX - ch_r, FCY, FCX - gap, FCY), (FCX + gap, FCY, FCX + ch_r, FCY),
                (FCX, FCY - ch_r, FCX, FCY - gap), (FCX, FCY + gap, FCX, FCY + ch_r)]:
            c.create_line(x1, y1, x2, y2, fill=ch_a, width=1)

        # Köşe braketleri
        blen = 22
        bc   = self._ac(0, 212, 255, 200)
        hl = FCX - FW // 2; hr = FCX + FW // 2
        ht = FCY - FW // 2; hb = FCY + FW // 2
        for bx, by, sdx, sdy in [(hl, ht, 1, 1), (hr, ht, -1, 1),
                                   (hl, hb, 1, -1), (hr, hb, -1, -1)]:
            c.create_line(bx, by, bx + sdx * blen, by,            fill=bc, width=2)
            c.create_line(bx, by, bx,               by + sdy * blen, fill=bc, width=2)

        # Yüz / orb
        if self._has_face:
            fw = int(FW * self.scale)
            if (self._face_scale_cache is None or
                    abs(self._face_scale_cache[0] - self.scale) > 0.004):
                scaled = self._face_pil.resize((fw, fw), Image.BILINEAR)
                # Mute'ta hafif kırmızı tint
                if self.muted:
                    tinted = scaled.copy()
                    r_ch, g_ch, b_ch, a_ch = tinted.split()
                    from PIL import ImageEnhance
                    g_ch = ImageEnhance.Brightness(
                        Image.fromarray(__import__('numpy').array(g_ch) // 2)
                    ).enhance(1.0) if False else g_ch   # basit: sadece önce cache
                tk_img = ImageTk.PhotoImage(scaled)
                self._face_scale_cache = (self.scale, tk_img)
            c.create_image(FCX, FCY, image=self._face_scale_cache[1])
        else:
            orb_r = int(FW * 0.27 * self.scale)
            orb_color = (255, 30, 80) if self.muted else (0, 65, 120)
            for i in range(7, 0, -1):
                r2   = int(orb_r * i / 7)
                frac = i / 7
                ga   = max(0, min(255, int(self.halo_a * 1.1 * frac)))
                c.create_oval(FCX-r2, FCY-r2, FCX+r2, FCY+r2,
                              fill=self._ac(int(orb_color[0]*frac),
                                            int(orb_color[1]*frac),
                                            int(orb_color[2]*frac), ga),
                              outline="")
            c.create_text(FCX, FCY, text=SYSTEM_NAME,
                          fill=self._ac(0, 212, 255, min(255, int(self.halo_a * 2))),
                          font=("Courier", 14, "bold"))

        # ── Header ────────────────────────────────────────────────────────────
        HDR = 62
        c.create_rectangle(0, 0, W, HDR, fill="#00080d", outline="")
        c.create_line(0, HDR, W, HDR, fill=C_MID, width=1)
        c.create_text(W // 2, 22, text=SYSTEM_NAME,
                      fill=C_PRI, font=("Courier", 18, "bold"))
        c.create_text(W // 2, 44, text="Just A Rather Very Intelligent System",
                      fill=C_MID, font=("Courier", 9))
        c.create_text(16, 31, text=MODEL_BADGE,
                      fill=C_DIM, font=("Courier", 9), anchor="w")
        c.create_text(W - 16, 31, text=time.strftime("%H:%M:%S"),
                      fill=C_PRI, font=("Courier", 14, "bold"), anchor="e")

        # ── Durum göstergesi ──────────────────────────────────────────────────
        sy = FCY + FW // 2 + 45

        if self.muted:
            stat = "⊘ MUTED"
            sc   = C_MUTED
        elif self.speaking:
            stat = "● SPEAKING"
            sc   = C_ACC
        elif self._jarvis_state == "THINKING":
            sym  = "◈" if self.status_blink else "◇"
            stat = f"{sym} THINKING"
            sc   = C_ACC2
        elif self._jarvis_state == "PROCESSING":
            sym  = "▷" if self.status_blink else "▶"
            stat = f"{sym} PROCESSING"
            sc   = C_ACC2
        elif self._jarvis_state == "LISTENING":
            sym  = "●" if self.status_blink else "○"
            stat = f"{sym} LISTENING"
            sc   = C_GREEN
        else:
            sym  = "●" if self.status_blink else "○"
            stat = f"{sym} {self.status_text}"
            sc   = C_PRI

        c.create_text(W // 2, sy, text=stat,
                      fill=sc, font=("Courier", 11, "bold"))

        # ── Ses dalgası ───────────────────────────────────────────────────────
        wy = sy + 22
        N  = 32
        BH = 18
        bw = 8
        total_w = N * bw
        wx0 = (W - total_w) // 2
        for i in range(N):
            if self.muted:
                hb  = 2
                col = C_MUTED
            elif self.speaking:
                hb  = random.randint(3, BH)
                col = C_PRI if hb > BH * 0.6 else C_MID
            else:
                hb  = int(3 + 2 * math.sin(t * 0.08 + i * 0.55))
                col = C_DIM
            bx = wx0 + i * bw
            c.create_rectangle(bx, wy + BH - hb, bx + bw - 1, wy + BH,
                                fill=col, outline="")

        # ── Footer ────────────────────────────────────────────────────────────
        c.create_rectangle(0, H - 28, W, H, fill="#00080d", outline="")
        c.create_line(0, H - 28, W, H - 28, fill=C_DIM, width=1)

        # F4 ipucu sağ tarafta
        c.create_text(W - 16, H - 14, fill=C_DIM, font=("Courier", 8),
                      text="[F4] MUTE", anchor="e")
        c.create_text(W // 2, H - 14, fill=C_DIM, font=("Courier", 8),
                      text="FatihMakes Industries  ·  CLASSIFIED  ·  MARK XXXV")

    # ── Log ───────────────────────────────────────────────────────────────────

    def write_log(self, text: str):
        self.typing_queue.append(text)
        tl = text.lower()

    # Overlay
        if tl.startswith("you:"):
            self.overlay.show_you(text[4:].strip())
            self.set_state("PROCESSING")
        elif tl.startswith("jarvis:") or tl.startswith("ai:"):
            self.overlay.show_ai(text[text.index(":")+1:].strip())
            self.set_state("SPEAKING")

        if not self.is_typing:
            self._start_typing()

    def _start_typing(self):
        if not self.typing_queue:
            self.is_typing = False
            if not self.speaking and not self.muted:
                self.set_state("LISTENING")
            return
        self.is_typing = True
        text = self.typing_queue.popleft()
        tl   = text.lower()
        if tl.startswith("you:"):
            tag = "you"
        elif tl.startswith("jarvis:") or tl.startswith("ai:"):
            tag = "ai"
        elif tl.startswith("err:") or "error" in tl or "failed" in tl:
            tag = "err"
        else:
            tag = "sys"
        self.log_text.configure(state="normal")
        self._type_char(text, 0, tag)

    def _type_char(self, text, i, tag):
        if i < len(text):
            self.log_text.insert(tk.END, text[i], tag)
            self.log_text.see(tk.END)
            self.root.after(8, self._type_char, text, i + 1, tag)
        else:
            self.log_text.insert(tk.END, "\n")
            self.log_text.configure(state="disabled")
            self.root.after(25, self._start_typing)

    # ── Eski compat metotlar (main.py hâlâ bunları çağırabilir) ──────────────

    def start_speaking(self):
        self.set_state("SPEAKING")

    def stop_speaking(self):
        if not self.muted:
            self.set_state("LISTENING")

    # ── API key ───────────────────────────────────────────────────────────────

    def _api_keys_exist(self):
        return API_FILE.exists()

    def wait_for_api_key(self):
        while not self._api_key_ready:
            time.sleep(0.1)

    def _show_setup_ui(self):
        self.setup_frame = tk.Frame(
            self.root, bg="#00080d",
            highlightbackground=C_PRI, highlightthickness=1
        )
        self.setup_frame.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(self.setup_frame, text="◈  INITIALISATION REQUIRED",
                 fg=C_PRI, bg="#00080d", font=("Courier", 13, "bold")).pack(pady=(18, 4))
        tk.Label(self.setup_frame,
                 text="Enter your Gemini API key to boot J.A.R.V.I.S.",
                 fg=C_MID, bg="#00080d", font=("Courier", 9)).pack(pady=(0, 10))

        tk.Label(self.setup_frame, text="GEMINI API KEY",
                 fg=C_DIM, bg="#00080d", font=("Courier", 9)).pack(pady=(8, 2))
        self.gemini_entry = tk.Entry(
            self.setup_frame, width=52, fg=C_TEXT, bg="#000d12",
            insertbackground=C_TEXT, borderwidth=0, font=("Courier", 10), show="*"
        )
        self.gemini_entry.pack(pady=(0, 4))

        tk.Button(
            self.setup_frame, text="▸  INITIALISE SYSTEMS",
            command=self._save_api_keys, bg=C_BG, fg=C_PRI,
            activebackground="#003344", font=("Courier", 10),
            borderwidth=0, pady=8
        ).pack(pady=14)

    def _save_api_keys(self):
        gemini = self.gemini_entry.get().strip()
        if not gemini:
            return
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(API_FILE, "w", encoding="utf-8") as f:
            json.dump({"gemini_api_key": gemini}, f, indent=4)
        self.setup_frame.destroy()
        self._api_key_ready = True
        self.set_state("LISTENING")
        self.write_log("SYS: Systems initialised. JARVIS online.")

# ── Overlay — agregar al final de jarvis_ui.py ────────────────────────────────

class JarvisOverlay:
    """
    Burbuja flotante pequeña, esquina inferior derecha.
    No roba foco, no interfiere con lo que el usuario esté haciendo.
    """

    W_OVERLAY  = 320
    PAD        = 12
    AUTO_HIDE  = 5000   # ms antes de ocultarse solo

    def __init__(self, root: tk.Tk):
        self._root     = root
        self._win      = None
        self._hide_job = None
        self._visible  = False
        self._create()

    def _create(self):
        self._win = tk.Toplevel(self._root)
        self._win.overrideredirect(True)          # sin bordes
        self._win.attributes("-topmost", True)    # siempre encima
        self._win.attributes("-alpha", 0.0)       # empieza invisible
        self._win.configure(bg="#000d12")

        # borde exterior
        self._frame = tk.Frame(
            self._win, bg="#000d12",
            highlightbackground="#00d4ff",
            highlightthickness=1,
        )
        self._frame.pack(fill="both", expand=True, padx=0, pady=0)

        # header pequeño
        self._header = tk.Label(
            self._frame,
            text="J.A.R.V.I.S",
            fg="#007a99", bg="#000d12",
            font=("Courier", 7, "bold"),
            anchor="w", padx=self.PAD,
        )
        self._header.pack(fill="x", pady=(6, 0))

        # texto usuario
        self._lbl_you = tk.Label(
            self._frame,
            text="",
            fg="#e8e8e8", bg="#000d12",
            font=("Courier", 9),
            wraplength=self.W_OVERLAY - self.PAD * 2,
            justify="left", anchor="w",
            padx=self.PAD,
        )
        self._lbl_you.pack(fill="x", pady=(2, 0))

        # separador
        self._sep = tk.Frame(self._frame, bg="#003344", height=1)
        self._sep.pack(fill="x", padx=self.PAD, pady=4)

        # texto jarvis
        self._lbl_ai = tk.Label(
            self._frame,
            text="",
            fg="#00d4ff", bg="#000d12",
            font=("Courier", 9),
            wraplength=self.W_OVERLAY - self.PAD * 2,
            justify="left", anchor="w",
            padx=self.PAD,
        )
        self._lbl_ai.pack(fill="x", pady=(0, self.PAD))

        self._position()
        self._win.withdraw()  # oculto al inicio

    def _position(self):
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        self._win.update_idletasks()
        h = self._win.winfo_reqheight()
        x = sw - self.W_OVERLAY - 16
        y = sh - h - 48           # encima de la barra de tareas
        self._win.geometry(f"{self.W_OVERLAY}x{h}+{x}+{y}")

    def _fade_in(self, alpha=0.0):
        if alpha >= 0.92:
            self._win.attributes("-alpha", 0.92)
            return
        self._win.attributes("-alpha", alpha)
        self._root.after(16, self._fade_in, alpha + 0.08)

    def _fade_out(self, alpha=0.92):
        if alpha <= 0.0:
            self._win.attributes("-alpha", 0.0)
            self._win.withdraw()
            self._visible = False
            return
        self._win.attributes("-alpha", alpha)
        self._root.after(20, self._fade_out, alpha - 0.07)

    def _schedule_hide(self):
        if self._hide_job:
            self._root.after_cancel(self._hide_job)
        self._hide_job = self._root.after(self.AUTO_HIDE, self._fade_out)

    def show_you(self, text: str):
        """Llamar cuando el usuario habla."""
        self._lbl_you.config(text=f"Vos: {text}")
        self._lbl_ai.config(text="")
        self._sep.config(bg="#003344")
        self._show()

    def show_ai(self, text: str):
        """Llamar cuando Jarvis responde."""
        self._lbl_ai.config(text=f"Jarvis: {text}")
        self._sep.config(bg="#00d4ff")
        self._show()
        self._schedule_hide()

    def _show(self):
        if self._hide_job:
            self._root.after_cancel(self._hide_job)
            self._hide_job = None
        if not self._visible:
            self._win.deiconify()
            self._visible = True
            self._fade_in()
        self._position()   # re-posicionar por si el texto cambió el alto

    def hide(self):
        self._fade_out()