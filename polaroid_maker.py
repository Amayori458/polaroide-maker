"""
Polaroid Maker
--------------
Monta automaticamente uma pasta inteira de fotos dentro de uma moldura
estilo polaroid, no tamanho exato pedido, prontas para importar no
software de album (ex: Smart Album) ou para impressao (ex: ima polaroid).

Dois modos:
  - Medidas manuais: voce digita o tamanho da moldura e da janela da foto
    em cm e o programa desenha uma moldura solida (branca ou de outra cor).
  - Mascara PSD: voce aponta para um arquivo .psd que ja tem a arte da
    moldura pronta (com uma camada de foto/smart object e uma camada de
    moldura com um "buraco" transparente). O programa encaixa a foto do
    cliente exatamente naquele buraco e funde com a arte por cima.

Como usar:
    1. Instale as dependencias (uma vez so):
         python -m pip install -r requirements.txt
    2. Rode:
         python polaroid_maker.py
    3. Escolha a pasta de entrada (fotos originais) e a pasta de saida.
    4. Escolha o modo e ajuste o que precisar.
    5. Clique em "Processar pasta".
"""

import os
import sys
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, colorchooser, messagebox, scrolledtext

from PIL import Image, ImageTk, ImageDraw, ImageColor

try:
    import numpy as np
    from psd_tools import PSDImage
    from psd_tools.constants import Resource
    from scipy import ndimage
    PSD_AVAILABLE = True
except ImportError:
    PSD_AVAILABLE = False

VALID_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
PSD_RESOLUTION_FIXED_POINT = 65536.0
PLACEHOLDER_NAMES = {"foto", "photo", "janela", "window", "picture", "imagem"}
EXPORT_DPI = 300  # todo projeto e' exportado em 300 dpi, sempre
# reforco escuro nos encontros das linhas de corte: um trecho da propria
# linha (nao um ponto), fino o bastante pra sumir quando o ima e' cortado
# em cima dela
# folha de ima: 20,3 x 15,2 cm (BOLA e Botao usam 21,6 x 15,2, definido nos atalhos)
SHEET_W_CM = 20.3
SHEET_H_CM = 15.2
CUT_MARK_ARM_CM = 0.6    # quanto cada braco do reforco se estende a partir do encontro
CUT_MARK_WIDTH_CM = 0.02  # espessura do reforco (a linha normal tem 0,01)
CUT_MARK_COLOR = (58, 58, 58, 255)  # cinza bem escuro (#3A3A3A), um pouco mais suave que o preto

# Atalhos para as mascaras de ima polaroid ja prontas.
PRESET_MASKS = {
    "Ima Horizontal": r"Y:\Matheus Oliveira\Gabaritos\Polaroide Imã\Polaroide Horizontal.psd",
    "Ima Vertical": r"Y:\Matheus Oliveira\Gabaritos\Polaroide Imã\Polaroide vertical.psd",
    "Folha Ima Horizontal (4x)": r"Y:\Matheus Oliveira\Gabaritos\Polaroide Imã\Polaroide ima Horizontal4x.psd",
    "Folha Ima Vertical (4x)": r"Y:\Matheus Oliveira\Gabaritos\Polaroide Imã\Polaroide ima Vertical4x.psd",
}

# Atalhos para grades simples (varias fotos por folha, sem arte de moldura),
# com os numeros tirados direto do painel "Album Info" do Smart Album.
PRESET_GRIDS = {
    "BOLA (6 fotos)": dict(
        sheet_w="21,6", sheet_h="15,2", cols="3", rows="2",
        photo_w="6,6", photo_h="6,6", border="0", gap="0",
        guide_color="#FFFFFF", guide_width="0",
        # bolinha: a foto e' recortada em circulo depois de impressa, entao
        # preenche o quadrado todo (corta o excesso) e fica na posicao em
        # que veio, sem girar; as bolinhas ficam encostadas nos cantos da
        # folha (0,2 cm de margem) e o resto vira vao branco no meio
        edge_margin="0,2",
        fit="cover", rotate="0",
    ),
    # botao: foto de 5,6x5,6 cm dentro de uma celula de 6,6 (borda branca de
    # 0,5 de cada lado = 1 cm de respiro entre os botoes pra faca circular),
    # 3 colunas x 2 linhas na folha de 21,6x15,2 -- igual ao projeto "Bottan"
    # do Smart Album. Encaixa a foto inteira e nao gira.
    "BOTAO (6 fotos)": dict(
        sheet_w="21,6", sheet_h="15,2", cols="3", rows="2",
        photo_w="6,6", photo_h="6,6", border="0,5", gap="0",
        guide_color="#FFFFFF", guide_width="0",
        fit="contain", rotate="0",
    ),
    "Ima 15x21 novo (4 fotos)": dict(
        # folha real de ima: 20,3 x 15,2. Cada ima ocupa exatamente 1/4 da
        # folha (10,15 x 7,6) com a borda branca de 0,28 em volta da foto,
        # entao so' se corta em cruz no meio -- sem aparar em volta.
        sheet_w="20,3", sheet_h="15,2", cols="2", rows="2",
        photo_w="10,15", photo_h="7,6", border="0,28", gap="0",
        guide_color="#B0B0B0", guide_width="0,01",
        fit="contain", rotate="auto", marks=True, outer_lines=False,
    ),
}

# ------------------------------------------------------------- visual ----
# Paleta extraida da logo da LAB Albuns (Y:\Matheus Oliveira\Site\logo)
ACCENT = "#8A5229"        # marrom medio (texto "ALBUNS" / corpo do livro)
ACCENT_DARK = "#431F19"   # marrom escuro/chocolate (texto "LAB" / lombada)
ACCENT_MID = "#683728"
BG = "#F7F1EA"
CARD_BG = "#FFFFFF"
BORDER = "#E1D3C2"
TEXT = "#3A2A20"
MUTED = "#8C7A6C"
GALLERY_BG = "#EFE4D6"
# quando empacotado com PyInstaller (--onefile), os arquivos extras (assets/)
# ficam numa pasta temporaria apontada por sys._MEIPASS, nao ao lado do .py
if getattr(sys, "frozen", False):
    APP_DIR = sys._MEIPASS
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(APP_DIR, "assets")
LOGO_HEADER_PATH = os.path.join(ASSETS_DIR, "logo_header.png")
LOGO_MARK_PATH = os.path.join(ASSETS_DIR, "icon_mark_final.png")
FONT = ("Segoe UI", 9)
FONT_BOLD = ("Segoe UI", 9, "bold")
FONT_HEADER = ("Segoe UI", 11, "bold")


def parse_float(text):
    text = text.strip().replace(",", ".")
    if not text:
        raise ValueError("valor vazio")
    return float(text)


def cm_to_px(cm, dpi):
    return round(cm / 2.54 * dpi)


def compute_margins(total_w, total_h, photo_w, photo_h, thick_side):
    """Calcula as 4 margens (esq, topo, dir, baixo) em cm no estilo
    polaroid classico: bordas finas e iguais em 3 lados, borda grossa
    (legenda) no lado escolhido. O eixo da borda grossa e' deduzido de
    qual diferenca (largura ou altura) e' maior."""
    diff_w = total_w - photo_w
    diff_h = total_h - photo_h
    if diff_w < 0 or diff_h < 0:
        raise ValueError(
            "A foto nao cabe na moldura (moldura menor que a janela da foto)."
        )

    if diff_w >= diff_h:
        axis = "horizontal"  # borda grossa fica na esquerda ou direita
        thin = diff_h / 2
        top = bottom = thin
        thick_margin = diff_w - thin
        if thick_side == "left":
            left, right = thick_margin, thin
        else:
            left, right = thin, thick_margin
    else:
        axis = "vertical"  # borda grossa fica em cima ou embaixo
        thin = diff_w / 2
        left = right = thin
        thick_margin = diff_h - thin
        if thick_side == "top":
            top, bottom = thick_margin, thin
        else:
            top, bottom = thin, thick_margin

    return left, top, right, bottom, axis


def cover_resize(img, target_w, target_h):
    """Redimensiona a imagem para cobrir exatamente target_w x target_h,
    cortando o excesso do centro (igual ao 'preencher' do Smart Album)."""
    src_w, src_h = img.size
    scale = max(target_w / src_w, target_h / src_h)
    new_w, new_h = max(1, round(src_w * scale)), max(1, round(src_h * scale))
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = round((new_w - target_w) / 2)
    top = round((new_h - target_h) / 2)
    img = img.crop((left, top, left + target_w, top + target_h))
    return img


def contain_resize(img, target_w, target_h, bg_color=(255, 255, 255)):
    """Redimensiona a imagem inteira pra caber dentro de target_w x
    target_h SEM cortar nada, e preenche o espaco que sobrar (nos dois
    lados de um dos eixos) com bg_color -- garante o tamanho exato sem
    perder nenhuma parte da foto."""
    src_w, src_h = img.size
    scale = min(target_w / src_w, target_h / src_h)
    new_w, new_h = max(1, round(src_w * scale)), max(1, round(src_h * scale))
    resized = img.resize((new_w, new_h), Image.LANCZOS)
    canvas = Image.new("RGB", (target_w, target_h), bg_color)
    canvas.paste(resized, ((target_w - new_w) // 2, (target_h - new_h) // 2))
    return canvas


def fit_photo(img, target_w, target_h, fit_mode="cover", bg_color=(255, 255, 255)):
    """Encaixa a foto em target_w x target_h no modo escolhido:
    'cover' (preenche e corta o excesso) ou 'contain' (encaixa a foto
    inteira sem cortar, com borda da cor bg_color onde sobrar espaco)."""
    if fit_mode == "contain":
        return contain_resize(img, target_w, target_h, bg_color)
    return cover_resize(img, target_w, target_h)


ROTATE_TRANSPOSE = {90: Image.ROTATE_270, 180: Image.ROTATE_180, 270: Image.ROTATE_90}
AUTO_ROTATE_PORTRAIT_DEG = 270  # graus aplicados a fotos em pe' no modo "automatica"


def load_photo(image_path, rotate_deg=0):
    """Abre a foto do cliente e devolve em RGB, com uma rotacao opcional
    (0/90/180/270 graus, sentido horario) -- ou "auto".

    Importante: NAO usamos a rotacao automatica via EXIF aqui. Fotos que
    circularam pelo WhatsApp costumam guardar uma tag de orientacao velha/
    incorreta que nao bate mais com os pixels (o WhatsApp ja reprocessou a
    imagem), e confiar nela vira as fotos de lado. O jeito confiavel e usar
    os pixels crus e, se alguma foto vier mesmo de lado, corrigir com a
    rotacao manual (no programa ou girando o arquivo antes).

    `rotate_deg="auto"`: fotos em pe' (retrato) giram
    AUTO_ROTATE_PORTRAIT_DEG (convencao dos gabaritos de polaroide, que sao
    impressos deitados e cortados/girados depois); fotos deitadas (paisagem)
    ficam do jeito que estao -- nao faz sentido girar uma foto que ja veio
    horizontal."""
    img = Image.open(image_path).convert("RGB")
    if rotate_deg == "auto":
        w, h = img.size
        rotate_deg = AUTO_ROTATE_PORTRAIT_DEG if h > w else 0
    op = ROTATE_TRANSPOSE.get(rotate_deg % 360)
    if op is not None:
        img = img.transpose(op)
    return img


def make_polaroid(image_path, total_w_px, total_h_px, photo_w_px, photo_h_px,
                   left_px, top_px, bg_color, rotate_deg=0, fit_mode="cover"):
    img = load_photo(image_path, rotate_deg)
    img = fit_photo(img, photo_w_px, photo_h_px, fit_mode, bg_color)
    canvas = Image.new("RGB", (total_w_px, total_h_px), bg_color)
    canvas.paste(img, (left_px, top_px))
    return canvas


# --------------------------------------------------------- modo mascara ----
def load_psd_mask(psd_path):
    """Le um PSD com uma ou mais camadas de foto (smart object) e uma ou
    mais camadas de moldura/arte. Devolve o tamanho do canvas, o DPI, a
    arte da moldura ja composta (RGBA, com os "buracos" transparentes onde
    as fotos devem entrar) e a lista de caixas (left, top, right, bottom)
    desses buracos, em ordem de leitura (topo->baixo, esquerda->direita).

    Funciona tanto para uma moldura com 1 foto quanto para uma folha de
    impressao com varias fotos (ex: folha com 4 imas), sem precisar saber
    de antemao quantos "slots" existem -- isso e' descoberto sozinho pelas
    areas transparentes da arte da moldura."""
    if not PSD_AVAILABLE:
        raise RuntimeError(
            "Falta instalar as bibliotecas para ler PSD. Rode:\n"
            "python -m pip install psd-tools numpy scipy"
        )

    psd = PSDImage.open(psd_path)
    canvas_w, canvas_h = psd.width, psd.height

    dpi = 300.0
    res = psd.image_resources.get(Resource.RESOLUTION_INFO)
    if res is not None and getattr(res.data, "horizontal", None):
        dpi = res.data.horizontal / PSD_RESOLUTION_FIXED_POINT

    frame_layers = []
    for layer in psd:
        is_placeholder = layer.kind == "smartobject" or layer.name.strip().lower() in PLACEHOLDER_NAMES
        if is_placeholder:
            continue
        frame_layers.append(layer)

    if not frame_layers:
        raise ValueError("Esse PSD so tem camada(s) de foto, nao achei a arte da moldura.")

    frame_img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    for layer in frame_layers:
        if not layer.is_visible():
            continue
        layer_img = layer.composite(viewport=psd.viewbox, force=True)
        if layer_img is not None:
            frame_img = Image.alpha_composite(frame_img, layer_img.convert("RGBA"))

    alpha = np.array(frame_img.split()[-1])
    transparent = alpha <= 5
    labeled, num_regions = ndimage.label(transparent)
    if num_regions == 0:
        raise ValueError(
            "Nao achei nenhuma area transparente na moldura (ela esta 100% opaca) "
            "-- confira se a camada da foto tem um buraco vazado."
        )

    slots = []
    for region_slice in ndimage.find_objects(labeled):
        if region_slice is None:
            continue
        y0, y1 = region_slice[0].start, region_slice[0].stop
        x0, x1 = region_slice[1].start, region_slice[1].stop
        if (x1 - x0) < 10 or (y1 - y0) < 10:
            continue  # ignora ruido/frestas minusculas, nao e' um slot de foto de verdade
        slots.append((x0, y0, x1, y1))

    if not slots:
        raise ValueError("Nao achei nenhuma janela de foto valida nessa moldura.")

    # ordem de leitura: linha por linha (topo->baixo), da esquerda pra direita
    slots.sort(key=lambda box: (box[1], box[0]))

    return {
        "path": psd_path,
        "canvas_size": (canvas_w, canvas_h),
        "dpi": dpi,
        "frame_rgba": frame_img,
        "slots": slots,
    }


def render_mask(photo_paths, mask, rotate_deg=0, rotations=None, fit_mode="cover", bg_color=(255, 255, 255)):
    """Encaixa uma lista de fotos (uma por slot, na ordem dos slots) na
    moldura/folha carregada e devolve a imagem final ja composta. Se a
    lista tiver menos fotos que slots, os slots restantes ficam em
    branco.

    `rotations`, se informado, e' uma lista paralela a photo_paths com a
    rotacao (graus) de cada foto individualmente; sem ela, usa `rotate_deg`
    para todas."""
    canvas_w, canvas_h = mask["canvas_size"]
    base = Image.new("RGB", (canvas_w, canvas_h), (255, 255, 255)).convert("RGBA")

    for i, (slot, photo_path) in enumerate(zip(mask["slots"], photo_paths)):
        if not photo_path:
            continue
        left, top, right, bottom = slot
        win_w, win_h = right - left, bottom - top
        deg = rotations[i] if rotations is not None else rotate_deg
        img = load_photo(photo_path, deg)
        img = fit_photo(img, win_w, win_h, fit_mode, bg_color)
        base.paste(img, (left, top))

    out = Image.alpha_composite(base, mask["frame_rgba"])
    return out.convert("RGB")


def make_masked_polaroid(image_path, mask, rotate_deg=0):
    return render_mask([image_path], mask, rotate_deg)


# ----------------------------------------------------------- modo grade ----
def build_grid_mask(sheet_w_cm, sheet_h_cm, cols, rows, photo_w_cm, photo_h_cm,
                     border_cm, gap_cm, dpi, bg_color="#FFFFFF",
                     guide_color="#999999", guide_width_cm=0, marks=False,
                     edge_margin_cm=0, outer_lines=True):
    """Monta uma 'mascara' sintetica pra uma grade simples de N fotos numa
    folha (sem nenhuma arte de moldura por baixo) -- devolve exatamente o
    mesmo formato de dicionario que load_psd_mask, entao todo o resto do
    programa (previa, galeria, lote) funciona sem saber a diferenca.

    `border_cm` e' uma faixa decorativa da cor de fundo desenhada pra
    dentro da propria celula (nao aumenta o tamanho da celula -- o
    "Frame W x H" que o Smart Album mostra ja e' o tamanho final).

    `guide_width_cm`, se maior que 0, desenha uma linha fina (cor
    `guide_color`) em volta de cada celula -- o "risco" que marca onde uma
    foto termina e a proxima comeca, pra servir de guia de corte.

    `marks`, se verdadeiro (so' vale com celulas coladas), escurece (preto)
    um trecho de cada linha da grade em volta de cada ponto onde elas se
    encontram -- e' onde o cortador apoia a regua na producao. O reforco
    fica em cima da propria linha, entao some junto com o corte.

    `edge_margin_cm`, se maior que 0, encosta a grade nos cantos da folha
    (deixa so' essa margem) e distribui o resto como vao branco entre as
    fotos, ignorando `gap_cm`.

    `outer_lines`, se falso, so' desenha as linhas (e reforcos) de DENTRO
    da grade -- as que separam uma foto da outra. Serve pra folha de ima
    onde cada ima ocupa 1/4 da folha e so' se corta no meio (um corte
    vertical e um horizontal), sem aparar em volta."""
    sheet_w_px = cm_to_px(sheet_w_cm, dpi)
    sheet_h_px = cm_to_px(sheet_h_cm, dpi)
    cell_w = cm_to_px(photo_w_cm, dpi)
    cell_h = cm_to_px(photo_h_cm, dpi)
    border_px = cm_to_px(border_cm, dpi)
    gap_x_px = gap_y_px = cm_to_px(gap_cm, dpi)

    if cols < 1 or rows < 1:
        raise ValueError("Numero de colunas/linhas precisa ser pelo menos 1.")
    if cell_w - 2 * border_px < 1 or cell_h - 2 * border_px < 1:
        raise ValueError("A borda esta grande demais pro tamanho da foto.")

    # arredondamento: 2 imas de 7,6 cm numa folha de 15,2 podem passar da
    # folha por 1-2 pixels -- se a grade passa so' por isso, encolhe a celula
    # em vez de dar erro
    if 0 < cols * cell_w + (cols - 1) * gap_x_px - sheet_w_px <= 2 * cols:
        cell_w = (sheet_w_px - (cols - 1) * gap_x_px) // cols
    if 0 < rows * cell_h + (rows - 1) * gap_y_px - sheet_h_px <= 2 * rows:
        cell_h = (sheet_h_px - (rows - 1) * gap_y_px) // rows

    edge_px = cm_to_px(edge_margin_cm, dpi)
    if edge_px > 0:
        # fotos empurradas pros cantos: so' sobra `edge_margin_cm` de
        # margem na folha e o resto vira vao branco entre elas (maior no
        # meio da folha). Substitui o espaco fixo entre fotos.
        if cols > 1:
            gap_x_px = max(0, (sheet_w_px - 2 * edge_px - cols * cell_w) // (cols - 1))
        if rows > 1:
            gap_y_px = max(0, (sheet_h_px - 2 * edge_px - rows * cell_h) // (rows - 1))
    gap_px = max(gap_x_px, gap_y_px)  # so' pra decidir o estilo das linhas/marcas

    grid_w = cols * cell_w + (cols - 1) * gap_x_px
    grid_h = rows * cell_h + (rows - 1) * gap_y_px
    if grid_w > sheet_w_px or grid_h > sheet_h_px:
        raise ValueError(
            f"A grade ({grid_w/dpi*2.54:.2f}x{grid_h/dpi*2.54:.2f}cm) nao cabe na "
            f"folha ({sheet_w_cm:.2f}x{sheet_h_cm:.2f}cm). Diminua a foto, a borda, "
            f"o espacamento, ou aumente a folha."
        )
    margin_x = (sheet_w_px - grid_w) // 2
    margin_y = (sheet_h_px - grid_h) // 2

    r, g, b = ImageColor.getrgb(bg_color)
    frame_rgba = Image.new("RGBA", (sheet_w_px, sheet_h_px), (r, g, b, 255))
    draw = ImageDraw.Draw(frame_rgba)

    guide_px = cm_to_px(guide_width_cm, dpi)
    guide_rgba = ImageColor.getrgb(guide_color) + (255,) if guide_px > 0 else None

    slots = []
    for row in range(rows):
        for col in range(cols):
            x0 = margin_x + col * (cell_w + gap_x_px)
            y0 = margin_y + row * (cell_h + gap_y_px)
            x1, y1 = x0 + cell_w, y0 + cell_h
            hx0, hy0 = x0 + border_px, y0 + border_px
            hx1, hy1 = x1 - border_px, y1 - border_px
            draw.rectangle([hx0, hy0, hx1 - 1, hy1 - 1], fill=(0, 0, 0, 0))
            slots.append((hx0, hy0, hx1, hy1))
            if guide_rgba is not None and gap_px > 0:
                draw.rectangle([x0, y0, x1 - 1, y1 - 1], outline=guide_rgba, width=guide_px)

    if guide_rgba is not None and gap_px == 0:
        # celulas coladas: cada linha da grade e' desenhada uma vez so', no
        # limite entre as celulas -- se cada celula desenhasse o proprio
        # contorno, as linhas do meio ficariam com o dobro da espessura (e
        # mais escuras) que as da borda de fora
        half = guide_px // 2
        top, bottom = margin_y, margin_y + rows * cell_h
        left, right = margin_x, margin_x + cols * cell_w
        col_range = range(cols + 1) if outer_lines else range(1, cols)
        row_range = range(rows + 1) if outer_lines else range(1, rows)
        for c in col_range:
            bx = margin_x + c * cell_w - half
            draw.rectangle([bx, top - half, bx + guide_px - 1, bottom - half + guide_px - 1], fill=guide_rgba)
        for r in row_range:
            by = margin_y + r * cell_h - half
            draw.rectangle([left - half, by, right - half + guide_px - 1, by + guide_px - 1], fill=guide_rgba)

    if marks and gap_px == 0:
        arm = cm_to_px(CUT_MARK_ARM_CM, dpi)
        mark_px = max(2, cm_to_px(CUT_MARK_WIDTH_CM, dpi))
        mhalf = mark_px // 2
        left, right = margin_x, margin_x + cols * cell_w
        top, bottom = margin_y, margin_y + rows * cell_h
        mark = CUT_MARK_COLOR
        for r in (range(rows + 1) if outer_lines else range(1, rows)):
            for c in (range(cols + 1) if outer_lines else range(1, cols)):
                cx = margin_x + c * cell_w
                cy = margin_y + r * cell_h
                # bracos recortados nos limites da grade: no canto vira um
                # "L", na borda um "T", no meio um "+"
                draw.rectangle([max(left, cx - arm), cy - mhalf,
                                min(right, cx + arm), cy - mhalf + mark_px - 1], fill=mark)
                draw.rectangle([cx - mhalf, max(top, cy - arm),
                                cx - mhalf + mark_px - 1, min(bottom, cy + arm)], fill=mark)
        if not outer_lines:
            # sem linha na borda externa: cada linha de corte de dentro
            # recebe o reforco tambem nas duas pontas, onde chega na borda
            # da folha (e' ali que a regua comeca)
            for c in range(1, cols):
                cx = margin_x + c * cell_w
                draw.rectangle([cx - mhalf, top, cx - mhalf + mark_px - 1, min(bottom, top + arm)], fill=mark)
                draw.rectangle([cx - mhalf, max(top, bottom - arm), cx - mhalf + mark_px - 1, bottom], fill=mark)
            for r in range(1, rows):
                cy = margin_y + r * cell_h
                draw.rectangle([left, cy - mhalf, min(right, left + arm), cy - mhalf + mark_px - 1], fill=mark)
                draw.rectangle([max(left, right - arm), cy - mhalf, right, cy - mhalf + mark_px - 1], fill=mark)

    return {
        "path": None,
        "canvas_size": (sheet_w_px, sheet_h_px),
        "dpi": dpi,
        "frame_rgba": frame_rgba,
        "slots": slots,
        "cols": cols,
        "rows": rows,
        # guarda os parametros originais pra poder remontar a grade com
        # menos fotos (regenerate_grid_for_count) quando sobrar um lote
        # incompleto no final da pasta -- assim nao fica metade da folha
        # em branco, os slots que sobrarem usam o espaco todo.
        "grid_params": dict(
            sheet_w_cm=sheet_w_cm, sheet_h_cm=sheet_h_cm,
            photo_w_cm=photo_w_cm, photo_h_cm=photo_h_cm,
            border_cm=border_cm, gap_cm=gap_cm, dpi=dpi, bg_color=bg_color,
            guide_color=guide_color, guide_width_cm=guide_width_cm, marks=marks,
            edge_margin_cm=edge_margin_cm, outer_lines=outer_lines,
        ),
    }


def regenerate_grid_for_count(mask, count):
    """Quando um lote no final da pasta tem menos fotos que a grade
    original comporta, tenta remontar a mesma grade (mesmo tamanho de
    folha e de foto) só com `count` fotos, numa unica coluna (empilhadas,
    uma embaixo da outra) centralizada -- pra nao sobrar uma folha com
    metade em branco. Se nao couber numa coluna so, tenta lado a lado; se
    nem isso couber, devolve a mascara original mesmo (aceita slots em
    branco, como antes)."""
    params = mask.get("grid_params")
    if not params or count >= len(mask["slots"]):
        return mask
    for cols, rows in ((1, count), (count, 1)):
        try:
            return build_grid_mask(
                params["sheet_w_cm"], params["sheet_h_cm"], cols, rows,
                params["photo_w_cm"], params["photo_h_cm"],
                params["border_cm"], params["gap_cm"], params["dpi"],
                params["bg_color"], guide_color=params["guide_color"],
                guide_width_cm=params["guide_width_cm"], marks=params.get("marks", False),
                edge_margin_cm=params.get("edge_margin_cm", 0),
                outer_lines=params.get("outer_lines", True),
            )
        except ValueError:
            continue
    return mask


def detect_art_lines(frame_rgba):
    """Acha as linhas cinza que o proprio PSD da folha ja traz desenhadas
    (as de corte): devolve (xs, ys) com o centro, em pixels, de cada linha
    vertical e horizontal que cruza a folha de ponta a ponta. So' olha
    pixels opacos -- as janelas das fotos sao transparentes."""
    import numpy as np
    arr = np.array(frame_rgba.convert("RGBA")).astype(int)
    opaque = arr[:, :, 3] > 0
    gray = arr[:, :, :3].mean(axis=2)
    line_px = opaque & (gray < 235)

    def centers(axis):
        n_opaque = opaque.sum(axis=axis)
        n_line = line_px.sum(axis=axis)
        is_line = (n_opaque > 0) & (n_line >= 0.9 * n_opaque) & (n_opaque >= 0.5 * opaque.shape[axis])
        found, start = [], None
        for i, v in enumerate(list(is_line) + [False]):
            if v and start is None:
                start = i
            elif not v and start is not None:
                found.append((start + i - 1) / 2)
                start = None
        return [round(c) for c in found]

    return centers(0), centers(1)


def prepare_sheet_mask(mask):
    """Folha com varias fotos: a folha impressa e' sempre SHEET_W_CM x
    SHEET_H_CM. Se o PSD for menor (ex: 20,3 x 15,2), aumenta a tela
    com margem branca, centralizado -- o tamanho dos imas nao muda. Tambem
    guarda onde estao as linhas de corte do PSD (art_lines) pra poder
    reforca-las. Mascara de uma foto so' (ima avulso) passa direto."""
    if len(mask["slots"]) < 2:
        return mask
    dpi = mask["dpi"]
    cw, ch = mask["canvas_size"]
    new_w = max(cw, cm_to_px(SHEET_W_CM, dpi))
    new_h = max(ch, cm_to_px(SHEET_H_CM, dpi))
    ox, oy = (new_w - cw) // 2, (new_h - ch) // 2
    frame = mask["frame_rgba"]
    xs, ys = detect_art_lines(frame)
    if (new_w, new_h) != (cw, ch):
        padded = Image.new("RGBA", (new_w, new_h), (255, 255, 255, 255))
        padded.paste(frame, (ox, oy))  # sem mascara: copia tambem a transparencia das janelas
        frame = padded
    out = dict(mask)
    out.update(
        canvas_size=(new_w, new_h),
        frame_rgba=frame,
        slots=[(l + ox, t + oy, r + ox, b + oy) for l, t, r, b in mask["slots"]],
        art_lines=([x + ox for x in xs], [y + oy for y in ys]),
    )
    return out


def with_cut_marks(mask):
    """Devolve uma copia da mascara com as linhas de corte do PSD reforcadas
    em preto onde se encontram (L nos cantos, T nas bordas, + no meio) --
    mesmo desenho do modo grade. Sem linhas detectadas, devolve igual."""
    xs, ys = mask.get("art_lines", ([], []))
    if len(xs) < 2 or len(ys) < 2:
        return mask
    dpi = mask["dpi"]
    arm = cm_to_px(CUT_MARK_ARM_CM, dpi)
    mark_px = max(2, cm_to_px(CUT_MARK_WIDTH_CM, dpi))
    mhalf = mark_px // 2
    left, right, top, bottom = min(xs), max(xs), min(ys), max(ys)
    frame = mask["frame_rgba"].copy()
    draw = ImageDraw.Draw(frame)
    for cy in ys:
        for cx in xs:
            draw.rectangle([max(left, cx - arm), cy - mhalf,
                            min(right, cx + arm), cy - mhalf + mark_px - 1], fill=CUT_MARK_COLOR)
            draw.rectangle([cx - mhalf, max(top, cy - arm),
                            cx - mhalf + mark_px - 1, min(bottom, cy + arm)], fill=CUT_MARK_COLOR)
    out = dict(mask)
    out["frame_rgba"] = frame
    return out


def fast_crop_thumb(image_path, rotate_deg, target_w, target_h, max_dim=170,
                     fit_mode="cover", bg_color=(255, 255, 255)):
    """Versao rapida do fit_photo pra miniaturas: encolhe o alvo pro
    tamanho de miniatura antes de processar, ao inves de processar em
    resolucao cheia e so depois encolher."""
    img = load_photo(image_path, rotate_deg)
    scale = max_dim / max(target_w, target_h)
    tw, th = max(1, round(target_w * scale)), max(1, round(target_h * scale))
    return fit_photo(img, tw, th, fit_mode, bg_color)


class PolaroidApp:
    def __init__(self, root):
        self.root = root
        root.title("Polaroid Maker")
        root.geometry("1180x760")
        root.minsize(1000, 640)

        self.bg_color = "#FFFFFF"
        self.log_queue = queue.Queue()
        self.preview_photo = None  # mantem referencia da imagem do preview
        self.mask_data = None
        self.photo_rotations = {}  # nome do arquivo -> rotacao (graus) individual
        self.gallery_widgets = {}  # nome do arquivo -> Label da miniatura

        self._setup_style()
        self._set_window_icon()
        self._build_ui()
        self._on_mode_change()
        self._recalc(preview=False)
        self.root.after(100, self._poll_queue)

    def _set_window_icon(self):
        try:
            icon_img = Image.open(LOGO_MARK_PATH).convert("RGBA")
            self._icon_photo = ImageTk.PhotoImage(icon_img)
            self.root.iconphoto(True, self._icon_photo)
        except Exception:
            pass

    # -------------------------------------------------------- estilo ----
    def _setup_style(self):
        self.root.configure(bg=BG)
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure(".", background=BG, foreground=TEXT, font=FONT)
        style.configure("TFrame", background=BG)
        style.configure("TLabelframe", background=BG, bordercolor=BORDER,
                         borderwidth=1, relief="solid")
        style.configure("TLabelframe.Label", background=BG, foreground=ACCENT_DARK, font=FONT_BOLD)
        style.configure("TLabel", background=BG, foreground=TEXT, font=FONT)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=FONT)
        style.configure("Header.TLabel", background=BG, foreground=TEXT, font=FONT_HEADER)
        style.configure("TRadiobutton", background=BG, foreground=TEXT, font=FONT)
        style.configure("TButton", padding=6, font=FONT)
        style.configure("Accent.TButton", padding=9, font=FONT_BOLD,
                         background=ACCENT, foreground="white")
        style.map("Accent.TButton",
                  background=[("active", ACCENT_DARK), ("disabled", "#DCCFC5")],
                  foreground=[("disabled", "#FFFFFF")])
        style.configure("TEntry", fieldbackground="white", padding=4)
        style.configure("TCombobox", fieldbackground="white", padding=4)
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(16, 8), font=FONT_BOLD)
        style.map("TNotebook.Tab", background=[("selected", CARD_BG)],
                  foreground=[("selected", ACCENT_DARK)])
        style.configure("Card.TFrame", background=CARD_BG, bordercolor=BORDER,
                         borderwidth=1, relief="solid")
        style.configure("Accent.Horizontal.TProgressbar", troughcolor=BORDER,
                         background=ACCENT, thickness=10)

    # ---------------------------------------------------------- UI ----
    def _build_ui(self):
        pad = {"padx": 8, "pady": 5}

        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=16, pady=(14, 0))
        try:
            logo_img = Image.open(LOGO_HEADER_PATH).convert("RGBA")
            target_h = 46
            target_w = max(1, round(logo_img.width * target_h / logo_img.height))
            logo_img = logo_img.resize((target_w, target_h), Image.LANCZOS)
            self.logo_photo = ImageTk.PhotoImage(logo_img)
            tk.Label(header, image=self.logo_photo, bg=BG).pack(side="left")
        except Exception:
            ttk.Label(header, text="LAB Albuns", style="Header.TLabel").pack(side="left")

        divider = tk.Frame(header, bg=BORDER, width=1, height=32)
        divider.pack(side="left", padx=14)
        title_box = ttk.Frame(header)
        title_box.pack(side="left")
        ttk.Label(title_box, text="Polaroid Maker", style="Header.TLabel").pack(anchor="w")
        ttk.Label(title_box, text="monta fotos em molduras polaroid automaticamente",
                  style="Muted.TLabel").pack(anchor="w")

        body = ttk.Frame(self.root)
        body.pack(fill="both", expand=True, padx=16, pady=12)

        # coluna esquerda com scroll (as vezes o conteudo nao cabe na tela)
        sidebar_container = ttk.Frame(body, width=310)
        sidebar_container.pack(side="left", fill="y")
        sidebar_container.pack_propagate(False)

        sidebar_canvas = tk.Canvas(sidebar_container, bg=BG, highlightthickness=0)
        sidebar_scroll = ttk.Scrollbar(sidebar_container, orient="vertical", command=sidebar_canvas.yview)
        left_col = ttk.Frame(sidebar_canvas)
        left_col.bind(
            "<Configure>",
            lambda e: sidebar_canvas.configure(scrollregion=sidebar_canvas.bbox("all")),
        )
        sidebar_window = sidebar_canvas.create_window((0, 0), window=left_col, anchor="nw")
        sidebar_canvas.configure(yscrollcommand=sidebar_scroll.set)
        sidebar_canvas.bind(
            "<Configure>",
            lambda e: sidebar_canvas.itemconfigure(sidebar_window, width=e.width),
        )
        sidebar_canvas.pack(side="left", fill="both", expand=True)
        sidebar_scroll.pack(side="right", fill="y")

        def on_sidebar_wheel(event):
            sidebar_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        sidebar_canvas.bind("<Enter>", lambda e: sidebar_canvas.bind_all("<MouseWheel>", on_sidebar_wheel))
        sidebar_canvas.bind("<Leave>", lambda e: sidebar_canvas.unbind_all("<MouseWheel>"))

        right_col = ttk.Frame(body)
        right_col.pack(side="right", fill="both", expand=True, padx=(14, 0))

        # ---- Pastas ----
        folders = ttk.LabelFrame(left_col, text="Pastas")
        folders.pack(fill="x", **pad)
        folders.columnconfigure(0, weight=1)

        self.in_dir = tk.StringVar()
        self.out_dir = tk.StringVar()

        ttk.Label(folders, text="Entrada:").grid(row=0, column=0, columnspan=2, sticky="w", padx=8, pady=(6, 0))
        ttk.Entry(folders, textvariable=self.in_dir).grid(row=1, column=0, sticky="we", padx=(8, 4), pady=2)
        ttk.Button(folders, text="Escolher...", command=self._pick_in).grid(row=1, column=1, padx=(0, 8))

        ttk.Label(folders, text="Saida:").grid(row=2, column=0, columnspan=2, sticky="w", padx=8, pady=(8, 0))
        ttk.Entry(folders, textvariable=self.out_dir).grid(row=3, column=0, sticky="we", padx=(8, 4), pady=(2, 8))
        ttk.Button(folders, text="Escolher...", command=self._pick_out).grid(row=3, column=1, padx=(0, 8), pady=(0, 8))

        # ---- Rotacao manual ----
        rotate_box = ttk.LabelFrame(left_col, text="Rotacao das fotos")
        rotate_box.pack(fill="x", **pad)
        ttk.Label(
            rotate_box,
            text="\"Automatica\" (padrao nos modos mascara/grade): cada\nfoto e' avaliada sozinha -- em pe' (retrato) gira 270,\ndeitada (paisagem) fica reta. Mude aqui se precisar\nforcar um angulo fixo pra pasta toda.",
            justify="left", style="Muted.TLabel",
        ).pack(anchor="w", padx=8, pady=(6, 4))
        self.rotate_deg = tk.StringVar(value="0")
        rotate_combo = ttk.Combobox(
            rotate_box, textvariable=self.rotate_deg, state="readonly", width=14,
            values=["auto", "0", "90", "180", "270"],
        )
        rotate_combo.pack(anchor="w", padx=8, pady=(0, 8))
        rotate_combo.bind("<<ComboboxSelected>>", lambda e: self._recalc(preview=True))

        ttk.Label(
            rotate_box,
            text="Fotos individuais fora do padrao? Gire cada uma na\naba \"Todas as fotos\" ao lado.",
            justify="left", style="Muted.TLabel",
        ).pack(anchor="w", padx=8, pady=(0, 8))

        # ---- Modo de encaixe ----
        fit_box = ttk.LabelFrame(left_col, text="Encaixe da foto na janela")
        fit_box.pack(fill="x", **pad)
        self.fit_mode = tk.StringVar(value="cover")  # ajustado por _on_mode_change/_load_mask conforme o modo
        ttk.Radiobutton(
            fit_box, text="Preencher e cortar o excesso", value="cover",
            variable=self.fit_mode, command=lambda: self._recalc(preview=True, rebuild_gallery=True),
        ).pack(anchor="w", padx=8, pady=(6, 0))
        ttk.Radiobutton(
            fit_box, text="Encaixar a foto inteira (com borda)", value="contain",
            variable=self.fit_mode, command=lambda: self._recalc(preview=True, rebuild_gallery=True),
        ).pack(anchor="w", padx=8, pady=(0, 4))
        ttk.Label(
            fit_box,
            text="\"Encaixar a foto inteira\" nunca corta ninguem, mas\npode sobrar uma faixa da cor abaixo nos dois lados\nquando a foto nao tem a mesma proporcao da janela.\n\n"
                 "Padrao automatico: imã/polaroide avulsa (1 foto) usa\n\"Preencher e cortar\"; folha com varias fotos usa\n\"Encaixar a foto inteira\". Pode trocar aqui quando quiser.",
            justify="left", style="Muted.TLabel",
        ).pack(anchor="w", padx=8, pady=(0, 6))

        color_row = ttk.Frame(fit_box)
        color_row.pack(anchor="w", padx=8, pady=(0, 8))
        ttk.Label(color_row, text="Cor da borda:").grid(row=0, column=0, padx=(0, 6))
        self.color_swatch = tk.Canvas(color_row, width=24, height=24, bg=self.bg_color,
                                       highlightthickness=1, highlightbackground=BORDER)
        self.color_swatch.grid(row=0, column=1, padx=(0, 6))
        ttk.Button(color_row, text="Escolher cor...", command=self._pick_color).grid(row=0, column=2)

        # ---- Modo ----
        mode_frame = ttk.LabelFrame(left_col, text="Tipo de moldura")
        mode_frame.pack(fill="x", **pad)
        self.mode = tk.StringVar(value="manual")
        ttk.Radiobutton(
            mode_frame, text="Medidas manuais (moldura solida)", value="manual",
            variable=self.mode, command=self._on_mode_change,
        ).pack(anchor="w", padx=8, pady=(6, 0))
        ttk.Radiobutton(
            mode_frame, text="Mascara PSD pronta", value="mask",
            variable=self.mode, command=self._on_mode_change,
        ).pack(anchor="w", padx=8, pady=(0, 0))
        ttk.Radiobutton(
            mode_frame, text="Grade simples (varias fotos por folha)", value="grid",
            variable=self.mode, command=self._on_mode_change,
        ).pack(anchor="w", padx=8, pady=(0, 8))

        # ---- Modo manual: container ----
        self.manual_frame = ttk.Frame(left_col)

        sizes = ttk.LabelFrame(self.manual_frame, text="Medidas (cm)")
        sizes.pack(fill="x", **pad)

        self.total_w = tk.StringVar(value="12,7")
        self.total_h = tk.StringVar(value="9")
        self.photo_w = tk.StringVar(value="8,77")
        self.photo_h = tk.StringVar(value="8,41")

        self._labeled_entry(sizes, "Moldura - largura", self.total_w, 0)
        self._labeled_entry(sizes, "Moldura - altura", self.total_h, 1)
        self._labeled_entry(sizes, "Foto - largura", self.photo_w, 2)
        self._labeled_entry(sizes, "Foto - altura", self.photo_h, 3)
        ttk.Label(sizes, text=f"Resolucao: sempre {EXPORT_DPI} dpi na exportacao",
                  style="Muted.TLabel").grid(row=4, column=0, columnspan=2, sticky="w", padx=8, pady=(2, 6))

        thick = ttk.LabelFrame(self.manual_frame, text="Lado da borda grossa (estilo polaroid)")
        thick.pack(fill="x", **pad)
        self.thick_side = tk.StringVar(value="right")
        self.thick_combo = ttk.Combobox(thick, textvariable=self.thick_side, state="readonly", width=14)
        self.thick_combo.pack(padx=8, pady=(8, 6), anchor="w")
        self.thick_combo.bind("<<ComboboxSelected>>", self._on_thick_change)

        self.margins_label = ttk.Label(thick, text="", justify="left", style="Muted.TLabel")
        self.margins_label.pack(padx=8, pady=(0, 8), anchor="w")

        for entry_var in (self.total_w, self.total_h, self.photo_w, self.photo_h):
            entry_var.trace_add("write", lambda *a: self._recalc())

        # ---- Modo mascara: container ----
        self.mask_frame = ttk.Frame(left_col)

        mask_box = ttk.LabelFrame(self.mask_frame, text="Arquivo .psd da mascara")
        mask_box.pack(fill="x", **pad)
        mask_box.columnconfigure(0, weight=1)

        # reforco escuro das linhas de corte nos encontros: a mesma opcao
        # vale pra grade simples e pras folhas de ima em PSD
        self.grid_marks = tk.BooleanVar(value=False)
        self.grid_outer_lines = tk.BooleanVar(value=True)  # linhas na borda externa da folha
        self.mask_base = None  # mascara do PSD sem o reforco, pra poder ligar/desligar

        self.mask_path = tk.StringVar()
        ttk.Entry(mask_box, textvariable=self.mask_path).grid(row=0, column=0, sticky="we", padx=(8, 4), pady=(8, 4))
        ttk.Button(mask_box, text="Escolher...", command=self._pick_psd).grid(row=0, column=1, padx=(0, 8), pady=(8, 4))

        presets_row = ttk.Frame(mask_box)
        presets_row.grid(row=1, column=0, columnspan=2, sticky="we", padx=8, pady=(2, 6))
        for name in PRESET_MASKS:
            ttk.Button(
                presets_row, text=name, width=15,
                command=lambda n=name: self._use_preset(n),
            ).pack(side="left", padx=(0, 4))

        ttk.Button(mask_box, text="Carregar mascara", command=self._load_mask).grid(
            row=2, column=0, columnspan=2, sticky="we", padx=8, pady=(0, 6)
        )

        self.mask_info_label = ttk.Label(mask_box, text="Nenhuma mascara carregada.",
                                          justify="left", wraplength=250, style="Muted.TLabel")
        self.mask_info_label.grid(row=3, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 8))

        ttk.Checkbutton(
            mask_box, text="Reforcar linhas onde se encontram\n(trecho mais escuro: onde apoiar a regua)",
            variable=self.grid_marks,
        ).grid(row=4, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 8))

        if not PSD_AVAILABLE:
            ttk.Label(
                mask_box,
                text="Falta instalar: pip install psd-tools numpy scipy",
                foreground="#B0402C", wraplength=250,
            ).grid(row=5, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 8))

        # ---- Modo grade simples: container ----
        self.grid_frame = ttk.Frame(left_col)

        grid_presets_box = ttk.LabelFrame(self.grid_frame, text="Atalhos")
        grid_presets_box.pack(fill="x", **pad)
        grid_presets_row = ttk.Frame(grid_presets_box)
        grid_presets_row.pack(fill="x", padx=8, pady=8)
        for name in PRESET_GRIDS:
            ttk.Button(
                grid_presets_row, text=name, width=17,
                command=lambda n=name: self._use_grid_preset(n),
            ).pack(side="left", padx=(0, 4))

        grid_sizes = ttk.LabelFrame(self.grid_frame, text="Folha e grade (cm)")
        grid_sizes.pack(fill="x", **pad)

        self.grid_sheet_w = tk.StringVar(value="21,6")
        self.grid_sheet_h = tk.StringVar(value="15,2")
        self.grid_cols = tk.StringVar(value="3")
        self.grid_rows = tk.StringVar(value="2")
        self.grid_photo_w = tk.StringVar(value="6,60")
        self.grid_photo_h = tk.StringVar(value="6,71")
        self.grid_border = tk.StringVar(value="0")
        self.grid_gap = tk.StringVar(value="0")
        self.grid_margin = tk.StringVar(value="0")

        self._labeled_entry(grid_sizes, "Folha - largura", self.grid_sheet_w, 0)
        self._labeled_entry(grid_sizes, "Folha - altura", self.grid_sheet_h, 1)
        self._labeled_entry(grid_sizes, "Colunas", self.grid_cols, 2)
        self._labeled_entry(grid_sizes, "Linhas", self.grid_rows, 3)
        self._labeled_entry(grid_sizes, "Foto - largura", self.grid_photo_w, 4)
        self._labeled_entry(grid_sizes, "Foto - altura", self.grid_photo_h, 5)
        self._labeled_entry(grid_sizes, "Borda por foto", self.grid_border, 6)
        self._labeled_entry(grid_sizes, "Espaco entre fotos", self.grid_gap, 7)
        self._labeled_entry(grid_sizes, "Margem nos cantos", self.grid_margin, 8)
        ttk.Label(grid_sizes, text="Margem nos cantos > 0 encosta as fotos nos cantos\nda folha e o espaco vira vao no meio (ignora o\nespaco entre fotos). 0 = fotos centralizadas.",
                  justify="left", style="Muted.TLabel").grid(row=9, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 4))
        ttk.Label(grid_sizes, text=f"Resolucao: sempre {EXPORT_DPI} dpi na exportacao",
                  style="Muted.TLabel").grid(row=10, column=0, columnspan=2, sticky="w", padx=8, pady=(2, 6))

        self.grid_info_label = ttk.Label(grid_sizes, text="", justify="left", style="Muted.TLabel", wraplength=260)
        self.grid_info_label.grid(row=11, column=0, columnspan=2, sticky="w", padx=8, pady=(4, 8))

        # ---- Linha de corte (o "risco" que marca onde cada foto termina) ----
        guide_box = ttk.LabelFrame(self.grid_frame, text="Linha de corte")
        guide_box.pack(fill="x", **pad)
        ttk.Label(
            guide_box,
            text="Linha fina em volta de cada foto, pra marcar onde\numa termina e a proxima comeca (0 = sem linha).",
            justify="left", style="Muted.TLabel",
        ).pack(anchor="w", padx=8, pady=(6, 4))

        self.grid_guide_width = tk.StringVar(value="0")
        guide_width_row = ttk.Frame(guide_box)
        guide_width_row.pack(anchor="w", padx=8, pady=(0, 4))
        ttk.Label(guide_width_row, text="Espessura (cm):").pack(side="left", padx=(0, 6))
        ttk.Entry(guide_width_row, textvariable=self.grid_guide_width, width=8).pack(side="left")

        self.grid_guide_color = "#999999"
        guide_color_row = ttk.Frame(guide_box)
        guide_color_row.pack(anchor="w", padx=8, pady=(0, 8))
        ttk.Label(guide_color_row, text="Cor:").pack(side="left", padx=(0, 6))
        self.grid_guide_swatch = tk.Canvas(guide_color_row, width=20, height=20, bg=self.grid_guide_color,
                                            highlightthickness=1, highlightbackground=BORDER)
        self.grid_guide_swatch.pack(side="left", padx=(0, 6))
        ttk.Button(guide_color_row, text="Escolher cor...", command=self._pick_grid_guide_color).pack(side="left")

        ttk.Checkbutton(
            guide_box, text="Reforcar linhas onde se encontram\n(trecho mais escuro: onde apoiar a regua)",
            variable=self.grid_marks,
        ).pack(anchor="w", padx=8, pady=(0, 8))
        self.grid_marks.trace_add("write", lambda *a: self._on_marks_toggle())

        ttk.Checkbutton(
            guide_box, text="Linhas tambem na borda externa da folha\n(desligado = so' o corte em cruz no meio)",
            variable=self.grid_outer_lines,
        ).pack(anchor="w", padx=8, pady=(0, 8))
        self.grid_outer_lines.trace_add("write", lambda *a: self._on_marks_toggle())

        for entry_var in (self.grid_sheet_w, self.grid_sheet_h, self.grid_cols, self.grid_rows,
                          self.grid_photo_w, self.grid_photo_h, self.grid_border, self.grid_gap,
                          self.grid_margin, self.grid_guide_width):
            entry_var.trace_add("write", lambda *a: self._recalc())

        # ---- Acoes ----
        actions = ttk.Frame(left_col)
        actions.pack(fill="x", padx=8, pady=(16, 4))
        ttk.Button(actions, text="Atualizar previa e galeria",
                   command=lambda: self._recalc(preview=True, rebuild_gallery=True)).pack(fill="x", pady=2)
        self.process_btn = ttk.Button(actions, text="Processar pasta", style="Accent.TButton",
                                       command=self._start_processing)
        self.process_btn.pack(fill="x", pady=(8, 2))

        self.progress = ttk.Progressbar(left_col, mode="determinate", style="Accent.Horizontal.TProgressbar")
        self.progress.pack(fill="x", padx=8, pady=(10, 0))

        # ---- Coluna direita: abas ----
        notebook = ttk.Notebook(right_col)
        notebook.pack(fill="both", expand=True)

        preview_tab = ttk.Frame(notebook, style="TFrame")
        gallery_tab = ttk.Frame(notebook, style="TFrame")
        log_tab = ttk.Frame(notebook, style="TFrame")
        notebook.add(preview_tab, text="Previa")
        notebook.add(gallery_tab, text="Todas as fotos")
        notebook.add(log_tab, text="Log")

        # -- aba Previa --
        ttk.Label(preview_tab, text="Previa da primeira foto / folha da pasta",
                  style="Muted.TLabel").pack(anchor="w", padx=4, pady=(8, 4))
        preview_card = ttk.Frame(preview_tab, style="Card.TFrame")
        preview_card.pack(fill="both", expand=True, padx=4, pady=(0, 8))
        self.preview_canvas = tk.Canvas(preview_card, bg=CARD_BG, highlightthickness=0)
        self.preview_canvas.pack(fill="both", expand=True, padx=1, pady=1)

        # -- aba Todas as fotos (galeria) --
        gallery_header = ttk.Frame(gallery_tab)
        gallery_header.pack(fill="x", padx=4, pady=(8, 4))
        ttk.Label(
            gallery_header,
            text="Previa de como cada foto fica cortada na moldura. Clique em \"Girar 90°\" pra corrigir uma foto de lado.",
            style="Muted.TLabel", wraplength=560, justify="left",
        ).pack(side="left")
        self.gallery_status = ttk.Label(gallery_header, text="", style="Muted.TLabel")
        self.gallery_status.pack(side="right")

        gallery_outer = ttk.Frame(gallery_tab, style="Card.TFrame")
        gallery_outer.pack(fill="both", expand=True, padx=4, pady=(0, 8))
        self.gallery_canvas = tk.Canvas(gallery_outer, bg=GALLERY_BG, highlightthickness=0)
        gallery_scroll = ttk.Scrollbar(gallery_outer, orient="vertical", command=self.gallery_canvas.yview)
        self.gallery_inner = tk.Frame(self.gallery_canvas, bg=GALLERY_BG)
        self.gallery_inner.bind(
            "<Configure>",
            lambda e: self.gallery_canvas.configure(scrollregion=self.gallery_canvas.bbox("all")),
        )
        self._gallery_window = self.gallery_canvas.create_window((0, 0), window=self.gallery_inner, anchor="nw")
        self.gallery_canvas.bind(
            "<Configure>",
            lambda e: self.gallery_canvas.itemconfigure(self._gallery_window, width=e.width),
        )
        self.gallery_canvas.configure(yscrollcommand=gallery_scroll.set)
        self.gallery_canvas.pack(side="left", fill="both", expand=True, padx=1, pady=1)
        gallery_scroll.pack(side="right", fill="y")

        def on_gallery_wheel(event):
            self.gallery_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self.gallery_canvas.bind("<Enter>", lambda e: self.gallery_canvas.bind_all("<MouseWheel>", on_gallery_wheel))
        self.gallery_canvas.bind("<Leave>", lambda e: self.gallery_canvas.unbind_all("<MouseWheel>"))

        # -- aba Log --
        ttk.Label(log_tab, text="Log do processamento", style="Muted.TLabel").pack(anchor="w", padx=4, pady=(8, 4))
        log_card = ttk.Frame(log_tab, style="Card.TFrame")
        log_card.pack(fill="both", expand=True, padx=4, pady=(0, 8))
        self.log_text = scrolledtext.ScrolledText(
            log_card, state="disabled", bg=CARD_BG, fg=TEXT,
            font=("Consolas", 9), borderwidth=0, highlightthickness=0,
        )
        self.log_text.pack(fill="both", expand=True, padx=1, pady=1)

    def _labeled_entry(self, parent, label, var, row):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=3)
        ttk.Entry(parent, textvariable=var, width=10).grid(row=row, column=1, sticky="w", padx=8, pady=3)

    # ------------------------------------------------------- helpers ----
    def _pick_in(self):
        d = filedialog.askdirectory(title="Pasta com as fotos originais")
        if d:
            self.in_dir.set(d)
            self.photo_rotations = {}
            self._recalc(preview=True, rebuild_gallery=True)

    def _pick_out(self):
        d = filedialog.askdirectory(title="Pasta de saida")
        if d:
            self.out_dir.set(d)

    def _pick_color(self):
        rgb, hex_color = colorchooser.askcolor(color=self.bg_color, title="Cor da borda")
        if hex_color:
            self.bg_color = hex_color
            self.color_swatch.configure(bg=hex_color)
            self._recalc(preview=True, rebuild_gallery=True)

    def _pick_grid_guide_color(self):
        rgb, hex_color = colorchooser.askcolor(color=self.grid_guide_color, title="Cor da linha de corte")
        if hex_color:
            self.grid_guide_color = hex_color
            self.grid_guide_swatch.configure(bg=hex_color)
            self._recalc(preview=True, rebuild_gallery=True)

    def _pick_psd(self):
        f = filedialog.askopenfilename(title="Escolha o arquivo .psd da mascara", filetypes=[("Photoshop", "*.psd *.psb")])
        if f:
            self.mask_path.set(f)
            self._load_mask()

    def _use_preset(self, name):
        if name.startswith("Folha Ima"):
            # folha de ima de 4 fotos: o layout novo (cada ima = 1/4 da folha
            # 20,3 x 15,2, so' corte em cruz no meio) e' montado pela grade;
            # as duas folhas em PSD ficaram com a mesma montagem e a rotacao
            # automatica cuida de foto em pe' / deitada
            self.mode.set("grid")
            self._on_mode_change()
            self._use_grid_preset("Ima 15x21 novo (4 fotos)")
            return
        self.mask_path.set(PRESET_MASKS[name])
        self._load_mask()

    def _log(self, msg):
        self.log_queue.put(("log", msg))

    def _poll_queue(self):
        try:
            while True:
                kind, *payload = self.log_queue.get_nowait()
                if kind == "log":
                    self.log_text.configure(state="normal")
                    self.log_text.insert("end", payload[0] + "\n")
                    self.log_text.see("end")
                    self.log_text.configure(state="disabled")
                elif kind == "progress":
                    i, total = payload
                    self.progress.configure(maximum=total, value=i)
                elif kind == "done":
                    self.process_btn.configure(state="normal")
                    messagebox.showinfo("Concluido", payload[0])
                elif kind == "gallery_thumb":
                    name, pil_img = payload
                    widget = self.gallery_widgets.get(name)
                    if widget is not None:
                        photo = ImageTk.PhotoImage(pil_img)
                        widget.configure(image=photo, text="")
                        widget.image = photo
                elif kind == "gallery_error":
                    name, msg = payload
                    widget = self.gallery_widgets.get(name)
                    if widget is not None:
                        widget.configure(text="erro ao ler", image="")
                elif kind == "gallery_status":
                    self.gallery_status.configure(text=payload[0])
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    # ----------------------------------------------------- modo ----
    def _on_mode_change(self):
        mode = self.mode.get()
        self.manual_frame.pack_forget()
        self.mask_frame.pack_forget()
        self.grid_frame.pack_forget()
        if mode == "manual":
            self.manual_frame.pack(fill="x")
            # o imã/polaroide avulso (1 foto) sempre preenche e corta --
            # e' o jeito classico da polaroide, sem borda branca sobrando
            self.fit_mode.set("cover")
            # medidas manuais nao tem a convencao de impressao rotacionada
            # dos gabaritos de ima -- sem rotacao por padrao
            self.rotate_deg.set("0")
        elif mode == "mask":
            self.mask_frame.pack(fill="x")
        else:
            self.grid_frame.pack(fill="x")
            # folha com varias fotos: nunca corta ninguem por padrao
            self.fit_mode.set("contain")
            self.rotate_deg.set("auto")
        self._recalc(preview=True, rebuild_gallery=True)

    def _use_grid_preset(self, name):
        preset = PRESET_GRIDS[name]
        self.grid_sheet_w.set(preset["sheet_w"])
        self.grid_sheet_h.set(preset["sheet_h"])
        self.grid_cols.set(preset["cols"])
        self.grid_rows.set(preset["rows"])
        self.grid_photo_w.set(preset["photo_w"])
        self.grid_photo_h.set(preset["photo_h"])
        self.grid_border.set(preset["border"])
        self.grid_gap.set(preset["gap"])
        self.grid_margin.set(preset.get("edge_margin", "0"))
        self.grid_guide_width.set(preset.get("guide_width", "0"))
        self.grid_guide_color = preset.get("guide_color", "#999999")
        self.grid_guide_swatch.configure(bg=self.grid_guide_color)
        self.grid_marks.set(preset.get("marks", False))
        self.grid_outer_lines.set(preset.get("outer_lines", True))
        self.fit_mode.set(preset.get("fit", "contain"))
        self.rotate_deg.set(preset.get("rotate", "auto"))
        self.photo_rotations = {}
        self._recalc(preview=True, rebuild_gallery=True)

    def _load_mask(self):
        path = self.mask_path.get().strip()
        if not path:
            messagebox.showerror("Erro", "Escolha um arquivo .psd primeiro.")
            return
        if not os.path.isfile(path):
            messagebox.showerror("Erro", f"Arquivo nao encontrado:\n{path}")
            return
        try:
            base = prepare_sheet_mask(load_psd_mask(path))
        except Exception as e:
            self.mask_data = None
            self.mask_base = None
            self.mask_info_label.configure(text=f"Erro ao carregar: {e}")
            self._log(f"Erro ao carregar mascara: {e}")
            return
        self.mask_base = base
        # folha de ima (varias fotos e linhas de corte no PSD): o reforco
        # escuro dos encontros ja vem ligado
        xs, ys = base.get("art_lines", ([], []))
        self._marks_guard = True
        self.grid_marks.set(len(xs) >= 2 and len(ys) >= 2)
        self._marks_guard = False
        self._apply_mask_marks()

        # fotos em pe' (retrato) colocadas numa mascara de polaroide
        # precisam girar 270 pra encaixar certo (convencao dos gabaritos
        # desse produto); fotos deitadas (paisagem) ficam retas -- por
        # isso o padrao e' "automatica", avaliando cada foto sozinha
        self.rotate_deg.set("auto")
        self.photo_rotations = {}

        cw, ch = self.mask_data["canvas_size"]
        dpi = self.mask_data["dpi"]
        slots = self.mask_data["slots"]
        # polaroide avulsa (1 foto por moldura): preenche e corta, como uma
        # polaroide de verdade. Folha com varias fotos: nunca corta ninguem.
        self.fit_mode.set("cover" if len(slots) == 1 else "contain")
        l, t, r, b = slots[0]
        win_w, win_h = r - l, b - t
        slots_line = (
            f"1 foto por moldura"
            if len(slots) == 1
            else f"{len(slots)} fotos por folha (uma folha a cada {len(slots)} fotos da pasta)"
        )
        self.mask_info_label.configure(
            text=(
                f"Tamanho: {cw/dpi*2.54:.2f} x {ch/dpi*2.54:.2f} cm ({cw}x{ch}px, PSD em {dpi:.0f} dpi)\n"
                f"Janela da foto: {win_w/dpi*2.54:.2f} x {win_h/dpi*2.54:.2f} cm\n"
                f"{slots_line}\n"
                f"Exportado sempre em {EXPORT_DPI} dpi."
            )
        )
        self._log(f"Mascara carregada: {os.path.basename(path)} ({len(slots)} slot(s))")
        self._recalc(preview=True, rebuild_gallery=True)

    def _apply_mask_marks(self):
        """Monta self.mask_data a partir do PSD carregado, com ou sem o
        reforco escuro nos encontros das linhas de corte."""
        if self.mask_base is None:
            return
        self.mask_data = with_cut_marks(self.mask_base) if self.grid_marks.get() else self.mask_base

    def _on_marks_toggle(self):
        if getattr(self, "_marks_guard", False):
            return
        if self.mode.get() == "mask":
            self._apply_mask_marks()
        self._recalc(preview=True)

    def _read_grid_sizes(self):
        sheet_w = parse_float(self.grid_sheet_w.get())
        sheet_h = parse_float(self.grid_sheet_h.get())
        cols = int(parse_float(self.grid_cols.get()))
        rows = int(parse_float(self.grid_rows.get()))
        photo_w = parse_float(self.grid_photo_w.get())
        photo_h = parse_float(self.grid_photo_h.get())
        border = parse_float(self.grid_border.get())
        gap = parse_float(self.grid_gap.get())  # 0 = fotos coladas (so' a BOLA tem espaco)
        dpi = EXPORT_DPI  # todo projeto e' exportado em 300 dpi, sempre
        guide_width = parse_float(self.grid_guide_width.get())
        return sheet_w, sheet_h, cols, rows, photo_w, photo_h, border, gap, dpi, guide_width

    def _rebuild_grid_mask(self):
        try:
            sheet_w, sheet_h, cols, rows, photo_w, photo_h, border, gap, dpi, guide_width = self._read_grid_sizes()
        except ValueError:
            return
        if cols * rows == 2 and cols < rows:
            # regra: uma grade CONFIGURADA de proposito com 2 fotos e'
            # sempre lado a lado (lateral) -- se o usuario configurou 1x2,
            # vira 2x1 sozinho. So vale pra grade configurada manualmente;
            # fotos que sobram no final de uma folha de 4 usam a regra
            # empilhada de regenerate_grid_for_count.
            cols, rows = rows, cols
        try:
            self.mask_data = build_grid_mask(
                sheet_w, sheet_h, cols, rows, photo_w, photo_h, border, gap, dpi, self.bg_color,
                guide_color=self.grid_guide_color, guide_width_cm=guide_width,
                marks=self.grid_marks.get(), edge_margin_cm=parse_float(self.grid_margin.get()),
                outer_lines=self.grid_outer_lines.get(),
            )
        except ValueError as e:
            self.mask_data = None
            self.grid_info_label.configure(text=str(e))
            return

        n_slots = len(self.mask_data["slots"])
        eff_cols, eff_rows = self.mask_data["cols"], self.mask_data["rows"]
        self.grid_info_label.configure(
            text=(
                f"Folha: {sheet_w:.2f}x{sheet_h:.2f}cm ({dpi:.0f} dpi)\n"
                f"{n_slots} fotos por folha ({eff_cols}x{eff_rows})"
            )
        )

    # ----------------------------------------------------- calculos ----
    def _read_sizes(self):
        total_w = parse_float(self.total_w.get())
        total_h = parse_float(self.total_h.get())
        photo_w = parse_float(self.photo_w.get())
        photo_h = parse_float(self.photo_h.get())
        dpi = EXPORT_DPI  # todo projeto e' exportado em 300 dpi, sempre
        return total_w, total_h, photo_w, photo_h, dpi

    def _recalc(self, preview=False, rebuild_gallery=False):
        mode = self.mode.get()
        if mode == "grid":
            self._rebuild_grid_mask()
            if preview:
                self._update_preview()
            if rebuild_gallery:
                self._build_gallery()
            return

        if mode == "mask":
            if preview:
                self._update_preview()
            if rebuild_gallery:
                self._build_gallery()
            return

        try:
            total_w, total_h, photo_w, photo_h, dpi = self._read_sizes()
        except ValueError:
            return

        diff_w = total_w - photo_w
        diff_h = total_h - photo_h
        axis = "horizontal" if diff_w >= diff_h else "vertical"
        options = ["left", "right"] if axis == "horizontal" else ["top", "bottom"]
        labels = {"left": "esquerda", "right": "direita", "top": "topo", "bottom": "baixo"}

        current = self.thick_side.get()
        if current not in options:
            current = options[1]
            self.thick_side.set(current)
        self.thick_combo.configure(values=[labels[o] for o in options])
        self.thick_combo.set(labels[current])
        # o combobox mostra o rotulo em pt-br mas guardamos o valor interno em ingles
        self._label_to_key = {labels[o]: o for o in options}

        try:
            left, top, right, bottom, axis = compute_margins(
                total_w, total_h, photo_w, photo_h, current
            )
        except ValueError as e:
            self.margins_label.configure(text=str(e))
            return

        self.margins_label.configure(
            text=(
                f"Esq: {left:.2f}cm  Topo: {top:.2f}cm\n"
                f"Dir: {right:.2f}cm  Baixo: {bottom:.2f}cm"
            )
        )
        self._current_margins = (left, top, right, bottom)

        if preview:
            self._update_preview()
        if rebuild_gallery:
            self._build_gallery()

    def _on_thick_change(self, event):
        label = self.thick_combo.get()
        key = self._label_to_key.get(label)
        if key:
            self.thick_side.set(key)
        self._recalc(preview=True, rebuild_gallery=True)

    def _read_rotate(self):
        val = self.rotate_deg.get()
        if val == "auto":
            return "auto"
        try:
            return int(val)
        except ValueError:
            return 0

    def _rotation_for(self, name):
        return self.photo_rotations.get(name, self._read_rotate())

    def _all_files(self):
        d = self.in_dir.get()
        if not d or not os.path.isdir(d):
            return []
        return [
            f for f in sorted(os.listdir(d))
            if os.path.splitext(f)[1].lower() in VALID_EXT
        ]

    def _first_image(self):
        images = self._first_images(1)
        return images[0] if images else None

    def _first_images(self, n):
        d = self.in_dir.get()
        if not d or not os.path.isdir(d):
            return []
        found = []
        for name in sorted(os.listdir(d)):
            if os.path.splitext(name)[1].lower() in VALID_EXT:
                found.append(os.path.join(d, name))
                if len(found) >= n:
                    break
        return found

    def _update_preview(self):
        if self.mode.get() != "manual":
            if self.mask_data is None:
                self.preview_canvas.delete("all")
                return
            canvas_w, canvas_h = self.mask_data["canvas_size"]
            n_slots = len(self.mask_data["slots"])
            img_paths = self._first_images(n_slots)
            if img_paths:
                try:
                    rotations = [self._rotation_for(os.path.basename(p)) for p in img_paths]
                    preview_mask = regenerate_grid_for_count(self.mask_data, len(img_paths))
                    canvas_img = render_mask(
                        img_paths, preview_mask, rotations=rotations,
                        fit_mode=self.fit_mode.get(), bg_color=self.bg_color,
                    )
                except Exception as e:
                    self._log(f"Erro na previa: {e}")
                    return
            else:
                canvas_img = Image.alpha_composite(
                    Image.new("RGBA", (canvas_w, canvas_h), (255, 255, 255, 255)),
                    self.mask_data["frame_rgba"],
                ).convert("RGB")
        else:
            img_path = self._first_image()
            try:
                total_w, total_h, photo_w, photo_h, dpi = self._read_sizes()
                left, top, right, bottom = self._current_margins
            except (ValueError, AttributeError):
                return

            total_w_px = cm_to_px(total_w, dpi)
            total_h_px = cm_to_px(total_h, dpi)
            photo_w_px = cm_to_px(photo_w, dpi)
            photo_h_px = cm_to_px(photo_h, dpi)
            left_px = cm_to_px(left, dpi)
            top_px = cm_to_px(top, dpi)

            if img_path:
                try:
                    canvas_img = make_polaroid(
                        img_path, total_w_px, total_h_px, photo_w_px, photo_h_px,
                        left_px, top_px, self.bg_color, self._rotation_for(os.path.basename(img_path)),
                        self.fit_mode.get(),
                    )
                except Exception as e:
                    self._log(f"Erro na previa: {e}")
                    return
            else:
                canvas_img = Image.new("RGB", (total_w_px, total_h_px), self.bg_color)

        cw, ch = self.preview_canvas.winfo_width(), self.preview_canvas.winfo_height()
        if cw <= 1:
            cw = 420
        if ch <= 1:
            ch = 340
        thumb = canvas_img.copy()
        thumb.thumbnail((cw - 20, ch - 20), Image.LANCZOS)
        self.preview_photo = ImageTk.PhotoImage(thumb)
        self.preview_canvas.delete("all")
        self.preview_canvas.create_image(cw // 2, ch // 2, image=self.preview_photo)

    # ------------------------------------------------------- galeria ----
    def _thumb_target_size(self):
        """Tamanho (px) da janela da foto usada pra recortar as miniaturas
        da galeria -- a janela do primeiro slot no modo mascara/grade, ou o
        tamanho da foto configurado no modo manual."""
        if self.mode.get() != "manual":
            if not self.mask_data:
                return None
            l, t, r, b = self.mask_data["slots"][0]
            return (r - l, b - t)
        try:
            total_w, total_h, photo_w, photo_h, dpi = self._read_sizes()
        except ValueError:
            return None
        return (cm_to_px(photo_w, dpi), cm_to_px(photo_h, dpi))

    def _build_gallery(self):
        for widget in self.gallery_inner.winfo_children():
            widget.destroy()
        self.gallery_widgets = {}

        files = self._all_files()
        if not files:
            tk.Label(self.gallery_inner, text="Nenhuma foto na pasta de entrada.",
                     bg=GALLERY_BG, fg=MUTED, font=FONT).grid(row=0, column=0, padx=12, pady=12)
            self.gallery_status.configure(text="")
            return

        target = self._thumb_target_size()
        cols = 5
        for idx, name in enumerate(files):
            r, c = divmod(idx, cols)
            cell = tk.Frame(self.gallery_inner, bg=CARD_BG, highlightbackground=BORDER,
                             highlightthickness=1, padx=8, pady=8)
            cell.grid(row=r, column=c, padx=8, pady=8, sticky="n")
            img_label = tk.Label(cell, bg=CARD_BG, width=170, height=130)
            img_label.pack()
            short_name = name if len(name) <= 22 else name[:19] + "..."
            tk.Label(cell, text=short_name, bg=CARD_BG, fg=TEXT, font=("Segoe UI", 8)).pack(pady=(6, 4))
            ttk.Button(
                cell, text="Girar 90°", width=12,
                command=lambda n=name, li=img_label: self._rotate_gallery_photo(n, li),
            ).pack()
            self.gallery_widgets[name] = img_label

        self.gallery_status.configure(text=f"Gerando previa de {len(files)} fotos...")
        d = self.in_dir.get()
        rotations = dict(self.photo_rotations)
        default_rotate = self._read_rotate()
        fit_mode = self.fit_mode.get()
        bg_color = self.bg_color
        thread = threading.Thread(
            target=self._gallery_worker,
            args=(d, files, rotations, default_rotate, target, fit_mode, bg_color),
            daemon=True,
        )
        thread.start()

    def _gallery_worker(self, d, files, rotations, default_rotate, target, fit_mode, bg_color):
        for name in files:
            path = os.path.join(d, name)
            deg = rotations.get(name, default_rotate)
            try:
                if target:
                    img = fast_crop_thumb(path, deg, target[0], target[1], fit_mode=fit_mode, bg_color=bg_color)
                else:
                    img = load_photo(path, deg)
                    img.thumbnail((170, 170), Image.LANCZOS)
                self.log_queue.put(("gallery_thumb", name, img))
            except Exception as e:
                self.log_queue.put(("gallery_error", name, str(e)))
        self.log_queue.put(("gallery_status", f"{len(files)} fotos"))

    def _rotate_gallery_photo(self, name, label_widget):
        current = self._rotation_for(name)
        current_deg = current if isinstance(current, int) else 0
        new_deg = (current_deg + 90) % 360
        self.photo_rotations[name] = new_deg
        path = os.path.join(self.in_dir.get(), name)
        target = self._thumb_target_size()
        try:
            if target:
                img = fast_crop_thumb(path, new_deg, target[0], target[1],
                                       fit_mode=self.fit_mode.get(), bg_color=self.bg_color)
            else:
                img = load_photo(path, new_deg)
                img.thumbnail((170, 170), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            label_widget.configure(image=photo)
            label_widget.image = photo
        except Exception:
            pass
        self._recalc(preview=True)

    # ---------------------------------------------------- processing ----
    def _start_processing(self):
        in_d = self.in_dir.get()
        out_d = self.out_dir.get()
        if not in_d or not os.path.isdir(in_d):
            messagebox.showerror("Erro", "Escolha uma pasta de entrada valida.")
            return
        if not out_d:
            messagebox.showerror("Erro", "Escolha uma pasta de saida.")
            return
        os.makedirs(out_d, exist_ok=True)

        files = self._all_files()
        if not files:
            messagebox.showwarning("Aviso", "Nenhuma imagem encontrada na pasta de entrada.")
            return

        if self.mode.get() != "manual":
            if self.mask_data is None:
                messagebox.showerror("Erro", "Carregue uma mascara (ou ajuste a grade) antes de processar.")
                return
            worker = self._process_worker_mask
            args = (
                in_d, out_d, files, self.mask_data, dict(self.photo_rotations),
                self._read_rotate(), self.fit_mode.get(), self.bg_color,
            )
        else:
            try:
                total_w, total_h, photo_w, photo_h, dpi = self._read_sizes()
                left, top, right, bottom = self._current_margins
            except (ValueError, AttributeError):
                messagebox.showerror("Erro", "Confira as medidas informadas.")
                return

            params = dict(
                total_w_px=cm_to_px(total_w, dpi),
                total_h_px=cm_to_px(total_h, dpi),
                photo_w_px=cm_to_px(photo_w, dpi),
                photo_h_px=cm_to_px(photo_h, dpi),
                left_px=cm_to_px(left, dpi),
                top_px=cm_to_px(top, dpi),
                bg_color=self.bg_color,
                dpi=dpi,
                rotate_deg=self._read_rotate(),
                fit_mode=self.fit_mode.get(),
            )
            worker = self._process_worker_manual
            args = (in_d, out_d, files, params, dict(self.photo_rotations))

        self.process_btn.configure(state="disabled")
        self.progress.configure(value=0, maximum=len(files))

        thread = threading.Thread(target=worker, args=args, daemon=True)
        thread.start()

    def _process_worker_manual(self, in_d, out_d, files, params, rotations=None):
        rotations = rotations or {}
        ok, failed = 0, 0
        for i, name in enumerate(files, start=1):
            src = os.path.join(in_d, name)
            base = os.path.splitext(name)[0]
            dst = os.path.join(out_d, f"{base}_polaroid.jpg")
            try:
                canvas = make_polaroid(
                    src, params["total_w_px"], params["total_h_px"],
                    params["photo_w_px"], params["photo_h_px"],
                    params["left_px"], params["top_px"], params["bg_color"],
                    rotations.get(name, params["rotate_deg"]), params["fit_mode"],
                )
                canvas.save(dst, "JPEG", quality=95, dpi=(params["dpi"], params["dpi"]))
                self._log(f"OK  - {name}")
                ok += 1
            except Exception as e:
                self._log(f"FALHA - {name}: {e}")
                failed += 1
            self.log_queue.put(("progress", i, len(files)))

        self.log_queue.put(("done", f"{ok} fotos processadas, {failed} falharam.\nSalvas em: {out_d}"))

    def _process_worker_mask(self, in_d, out_d, files, mask, rotations=None, rotate_deg=0,
                              fit_mode="cover", bg_color=(255, 255, 255)):
        rotations = rotations or {}
        dpi = EXPORT_DPI  # todo projeto e' exportado em 300 dpi, sempre (nao usa o dpi do PSD)
        n_slots = len(mask["slots"])

        if n_slots == 1:
            ok, failed = 0, 0
            for i, name in enumerate(files, start=1):
                src = os.path.join(in_d, name)
                base = os.path.splitext(name)[0]
                dst = os.path.join(out_d, f"{base}_polaroid.jpg")
                try:
                    canvas = render_mask([src], mask, rotations.get(name, rotate_deg),
                                          fit_mode=fit_mode, bg_color=bg_color)
                    canvas.save(dst, "JPEG", quality=95, dpi=(dpi, dpi))
                    self._log(f"OK  - {name}")
                    ok += 1
                except Exception as e:
                    self._log(f"FALHA - {name}: {e}")
                    failed += 1
                self.log_queue.put(("progress", i, len(files)))
            self.log_queue.put(("done", f"{ok} fotos processadas, {failed} falharam.\nSalvas em: {out_d}"))
            return

        # varios slots por folha: agrupa as fotos em lotes e gera uma folha
        # por lote. Se o ultimo lote sobrar incompleto (menos fotos que
        # n_slots), a grade e' remontada so com as fotos que sobraram --
        # empilhadas (uma coluna, uma embaixo da outra) preenchendo a
        # folha toda, sem sobrar metade em branco.
        groups = [files[i:i + n_slots] for i in range(0, len(files), n_slots)]
        ok, failed = 0, 0
        for i, group in enumerate(groups, start=1):
            srcs = [os.path.join(in_d, name) for name in group]
            group_rotations = [rotations.get(name, rotate_deg) for name in group]
            dst = os.path.join(out_d, f"folha_{i:03d}.jpg")
            try:
                group_mask = regenerate_grid_for_count(mask, len(group))
                faltando = len(group_mask["slots"]) - len(group)
                canvas = render_mask(srcs, group_mask, rotations=group_rotations, fit_mode=fit_mode, bg_color=bg_color)
                canvas.save(dst, "JPEG", quality=95, dpi=(dpi, dpi))
                extra = f" ({faltando} espaco(s) em branco)" if faltando else ""
                remontada = " [grade remontada pra caber sem sobrar espaco]" if group_mask is not mask else ""
                self._log(f"OK  - folha_{i:03d}.jpg <- {', '.join(group)}{extra}{remontada}")
                ok += 1
            except Exception as e:
                self._log(f"FALHA - folha_{i:03d}.jpg: {e}")
                failed += 1
            self.log_queue.put(("progress", i, len(groups)))

        self.log_queue.put((
            "done",
            f"{ok} folha(s) geradas ({len(files)} fotos, {n_slots} por folha), {failed} falharam.\nSalvas em: {out_d}",
        ))


def main():
    root = tk.Tk()
    app = PolaroidApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
