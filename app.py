import streamlit as st
import uuid
import os
import math
import base64
import json
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps
import io
import zipfile
from streamlit_image_coordinates import streamlit_image_coordinates
from streamlit_image_comparison import image_comparison
from streamlit_drawable_canvas import st_canvas

# === 页面配置 ===
st.set_page_config(page_title="图片工具箱 Pro Max", layout="wide", page_icon="🛠️")
Image.MAX_IMAGE_PIXELS = None

# === CSS 样式 ===
st.markdown("""
    <style>
    .stTabs [data-baseweb="tab-list"] { gap: 24px; }
    .stTabs [data-baseweb="tab"] { height: 50px; white-space: pre-wrap; background-color: #f0f2f6; border-radius: 4px 4px 0 0; gap: 1px; padding-top: 10px; padding-bottom: 10px; }
    .stTabs [aria-selected="true"] { background-color: #ffffff; border-top: 2px solid #ff4b4b; }
    div[data-testid="stImage"] img { object-fit: contain; }
    </style>
""", unsafe_allow_html=True)

# === Session State 初始化 ===
for key in ['x_cuts', 'y_cuts', 'last_click', 'stitched_result', 'restored_image', 'original_for_restore']:
    if key not in st.session_state: st.session_state[key] = None if 'list' not in str(type(st.session_state.get(key))) else []

if 'x_cuts' not in st.session_state: st.session_state['x_cuts'] = []
if 'y_cuts' not in st.session_state: st.session_state['y_cuts'] = []
if 'cut_history' not in st.session_state: st.session_state['cut_history'] = []

# Tab 4 专用状态
if 'canvas_locked' not in st.session_state: st.session_state['canvas_locked'] = False
if 'locked_scale' not in st.session_state: st.session_state['locked_scale'] = 1.0
if 'canvas_key' not in st.session_state: st.session_state['canvas_key'] = "init"
if 'canvas_bg_json' not in st.session_state: st.session_state['canvas_bg_json'] = None
if 'saved_rects' not in st.session_state: st.session_state['saved_rects'] = [] 
if 'frozen_drawing' not in st.session_state: st.session_state['frozen_drawing'] = None
if 'last_draw_mode' not in st.session_state: st.session_state['last_draw_mode'] = "✏️ 画框模式"

# Tab 6 (标注) 专用状态
if 'annotate_locked' not in st.session_state: st.session_state['annotate_locked'] = False
if 'annotate_scale' not in st.session_state: st.session_state['annotate_scale'] = 1.0
if 'annotate_key' not in st.session_state: st.session_state['annotate_key'] = "init_anno"
if 'annotate_bg_base64' not in st.session_state: st.session_state['annotate_bg_base64'] = None
if 'annotate_objects' not in st.session_state: st.session_state['annotate_objects'] = [] # 存储画的对象
if 'show_anno_result' not in st.session_state: st.session_state['show_anno_result'] = False

# === 工具函数 ===

def convert_image_to_bytes(img, fmt='PNG'):
    buf = io.BytesIO()
    if fmt.upper() in ['JPEG', 'JPG']: img.save(buf, format=fmt, quality=100, subsampling=0)
    else: img.save(buf, format=fmt)
    return buf.getvalue()

def image_to_base64(img):
    buffered = io.BytesIO()
    if img.mode in ("RGBA", "P"): img = img.convert("RGB")
    img.save(buffered, format="JPEG", quality=70)
    img_str = base64.b64encode(buffered.getvalue()).decode()
    return f"data:image/jpeg;base64,{img_str}"

@st.cache_data(show_spinner=False)
def process_uploaded_image(uploaded_file):
    try:
        uploaded_file.seek(0)
        file_bytes = uploaded_file.read()
        img = Image.open(io.BytesIO(file_bytes))
        try:
            if hasattr(img, '_getexif'):
                img = ImageOps.exif_transpose(img)
        except: pass 
        
        new_img = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
            if img.mode != 'RGBA': img = img.convert('RGBA')
            new_img.paste(img, mask=img.split()[3])
        else:
            new_img.paste(img)
        return new_img
    except Exception:
        return Image.new('RGB', (200, 50), (255, 200, 200))

def clean_image(uploaded_file):
    return process_uploaded_image(uploaded_file)

def enhance_image(image, upscale_factor=2.0, sharpness=2.0, contrast=1.1, color=1.1):
    if upscale_factor > 1.0:
        new_w, new_h = int(image.width * upscale_factor), int(image.height * upscale_factor)
        img = image.resize((new_w, new_h), Image.Resampling.LANCZOS)
    else: img = image.copy()
    img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3))
    img = ImageEnhance.Contrast(img).enhance(contrast)
    img = ImageEnhance.Color(img).enhance(color)
    img = ImageEnhance.Sharpness(img).enhance(sharpness)
    return img

def slice_image_by_guides(img, xs, ys):
    xs = sorted(list(set([0] + xs + [img.width])))
    ys = sorted(list(set([0] + ys + [img.height])))
    return [img.crop((xs[i], ys[j], xs[i+1], ys[j+1])) for j in range(len(ys)-1) for i in range(len(xs)-1) if xs[i+1]>xs[i] and ys[j+1]>ys[j]]

def stitch_images_advanced(images_data, mode='vertical', alignment='max', cols=2, padding=0, bg_color='#FFFFFF'):
    if not images_data: return None
    bg_color_rgb = tuple(int(bg_color.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))

    processed_inputs = []
    for item in images_data:
        img = item['img']
        scale = item['scale']
        rotate = item['rotate']
        if rotate != 0: img = img.rotate(-rotate, expand=True)
        if scale != 1.0:
            new_w, new_h = int(img.width * scale), int(img.height * scale)
            if new_w > 0 and new_h > 0: img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        processed_inputs.append(img)

    images = processed_inputs 

    if mode == 'vertical':
        max_width = max(img.width for img in images)
        final_imgs = []
        for img in images:
            if alignment == 'max' and img.width != max_width:
                ratio = max_width / img.width
                new_height = int(img.height * ratio)
                img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
            final_imgs.append(img)
        total_height = sum(img.height for img in final_imgs) + (len(final_imgs) - 1) * padding
        result = Image.new('RGB', (max_width, total_height), bg_color_rgb)
        y_offset = 0
        for img in final_imgs:
            x_center = (max_width - img.width) // 2
            result.paste(img, (x_center, y_offset))
            y_offset += img.height + padding
            
    elif mode == 'horizontal':
        max_height = max(img.height for img in images)
        final_imgs = []
        for img in images:
            if alignment == 'max' and img.height != max_height:
                ratio = max_height / img.height
                new_width = int(img.width * ratio)
                img = img.resize((new_width, max_height), Image.Resampling.LANCZOS)
            final_imgs.append(img)
        total_width = sum(img.width for img in final_imgs) + (len(final_imgs) - 1) * padding
        result = Image.new('RGB', (total_width, max_height), bg_color_rgb)
        x_offset = 0
        for img in final_imgs:
            y_center = (max_height - img.height) // 2
            result.paste(img, (x_offset, y_center))
            x_offset += img.width + padding

    else: 
        target_width = max(img.width for img in images)
        resized_imgs = []
        for img in images:
            if alignment == 'max':
                ratio = target_width / img.width
                new_h = int(img.height * ratio)
                img = img.resize((target_width, new_h), Image.Resampling.LANCZOS)
            resized_imgs.append(img)
        num_images = len(resized_imgs)
        rows = math.ceil(num_images / cols)
        row_heights = []
        for r in range(rows):
            row_imgs = resized_imgs[r*cols : (r+1)*cols]
            if row_imgs: max_h_in_row = max(img.height for img in row_imgs)
            else: max_h_in_row = 0
            row_heights.append(max_h_in_row)
        total_w = cols * target_width + (cols - 1) * padding
        total_h = sum(row_heights) + (rows - 1) * padding
        result = Image.new('RGB', (total_w, total_h), bg_color_rgb)
        for i, img in enumerate(resized_imgs):
            r = i // cols
            c = i % cols
            x = c * (target_width + padding)
            y = sum(row_heights[:r]) + r * padding
            x_center = x + (target_width - img.width) // 2
            row_h = row_heights[r]
            y_center = y + (row_h - img.height) // 2
            result.paste(img, (x_center, y_center))
            
    return result

# === 主界面 ===
st.title("🛠️ 全能图片工具箱 Pro Max")

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["🧩 智能拼图", "🔪 参考线切图", "💎 高清修复", "🔳 自由框选切割", "🎨 自由画布", "📝 图片标注 (稳定版)"])

# --- Tab 1: 拼图 ---
with tab1:
    st.header("图片拼接")
    files = st.file_uploader("上传图片", type=['png','jpg','jpeg','webp'], accept_multiple_files=True, key="stitch_up")
    
    if files:
        st.info("👇 **单张图片调整区** (排序、缩放、旋转)")
        image_settings = []
        for i, f in enumerate(files):
            with st.container():
                c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
                with c1:
                    try:
                        img_safe = clean_image(f)
                        st.image(img_safe, use_column_width=True)
                    except:
                        st.error("图片错误")
                        continue
                with c2:
                    rank = st.number_input(f"顺序", min_value=1, value=i+1, key=f"rank_{i}")
                with c3:
                    scale = st.slider(f"缩放", 0.1, 2.0, 1.0, 0.1, key=f"scale_{i}")
                with c4:
                    rotate = st.selectbox(f"旋转", [0, 90, 180, 270], key=f"rot_{i}", format_func=lambda x: f"🔄 {x}°")
                image_settings.append({"file": f,"img": img_safe,"rank": rank,"scale": scale,"rotate": rotate})
                st.divider()

        sorted_settings = sorted(image_settings, key=lambda x: x["rank"])
        
        st.markdown("### ⚙️ 全局设置")
        c1, c2, c3 = st.columns([1, 1, 1])
        with c1:
            stitch_mode = st.radio("拼接模式", ['vertical', 'horizontal', 'grid'], 
                                   format_func=lambda x: "⬇️ 竖向" if x=='vertical' else ("➡️ 横向" if x=='horizontal' else "田 网格"))
        with c2:
            if stitch_mode != 'grid':
                align_mode = st.radio("对齐方式", ['max', 'original'], format_func=lambda x: "📏 自动拉伸" if x=='max' else "🔳 保持原图")
            else:
                grid_cols = st.number_input("列数", 1, 10, 2)
                align_mode = 'max'
        with c3:
            padding = st.slider("间距", 0, 100, 0)
            bg_color = st.color_picker("背景色", "#FFFFFF")

        if st.button("✨ 开始拼接", type="primary", use_container_width=True):
            try:
                cols_param = grid_cols if stitch_mode == 'grid' else 1
                st.session_state['stitched_result'] = stitch_images_advanced(
                    sorted_settings, mode=stitch_mode, alignment=align_mode, cols=cols_param, padding=padding, bg_color=bg_color
                )
            except Exception as e:
                st.error(f"拼接错误: {e}")
            
    if st.session_state['stitched_result']:
        res = st.session_state['stitched_result']
        st.success(f"拼接完成！尺寸: {res.width} x {res.height}")
        col_view1, col_view2 = st.columns([1, 3])
        with col_view1:
            st.markdown("**预览设置：**")
            fit_screen = st.checkbox("📺 适应窗口宽度", value=True, key="fit_screen_check")
            if not fit_screen:
                zoom_factor = st.slider("🔍 像素缩放 (%)", 1, 100, 20, key="pixel_zoom_slider")
            else:
                st.caption("已锁定适应窗口宽度")

        st.download_button("📥 下载拼接大图", convert_image_to_bytes(res), "stitch.png", "image/png", type="primary", use_container_width=True)
        if fit_screen:
            st.image(res, use_column_width=True, caption="预览 (适应窗口)")
        else:
            new_w = max(1, int(res.width * zoom_factor / 100))
            st.image(res, width=new_w, caption=f"预览 ({zoom_factor}%)")

# --- Tab 2: 参考线切图 ---
with tab2:
    st.header("参考线贯穿切割 (Guillotine)")
    f = st.file_uploader("上传图片", type=['png','jpg','jpeg'], key="sl_up")
    if f:
        img = clean_image(f)
        if 'current_img' not in st.session_state or st.session_state.current_img != f.name:
            st.session_state.x_cuts, st.session_state.y_cuts = [], []
            st.session_state.cut_history = []
            st.session_state.current_img = f.name
            
        c1, c2 = st.columns([1, 2])
        with c1:
            z = st.slider("缩放", 10, 100, 100, 10, key="sl_z") / 100.0
            st.write("---")
            op_mode = st.radio("操作模式", ["➕ 添加参考线", "✋ 移动/调整参考线"], horizontal=True)
            if op_mode == "✋ 移动/调整参考线": st.info("点击参考线附近可移动它")
            line_type = st.radio("类型", ["⬇️ 垂直线", "➡️ 水平线"])
            st.caption(f"X: {sorted(st.session_state.x_cuts)}")
            st.caption(f"Y: {sorted(st.session_state.y_cuts)}")
            b_col1, b_col2 = st.columns(2)
            with b_col1:
                if st.button("🗑️ 清空", use_container_width=True): 
                    st.session_state.x_cuts, st.session_state.y_cuts = [], []
                    st.session_state.cut_history = []
                    st.rerun()
            with b_col2:
                if st.button("↩️ 撤销", use_container_width=True):
                    if st.session_state.cut_history:
                        last_type, last_val = st.session_state.cut_history.pop()
                        if last_type == 'x' and last_val in st.session_state.x_cuts: st.session_state.x_cuts.remove(last_val)
                        elif last_type == 'y' and last_val in st.session_state.y_cuts: st.session_state.y_cuts.remove(last_val)
                        st.rerun()
            st.write("---")
            if st.button("✂️ 切割下载", type="primary", use_container_width=True):
                slices = slice_image_by_guides(img, st.session_state.x_cuts, st.session_state.y_cuts)
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w") as zf:
                    for i, s in enumerate(slices):
                        b = io.BytesIO(); s.save(b, 'PNG'); zf.writestr(f"slice_{i+1}.png", b.getvalue())
                st.download_button("📦 下载ZIP", buf.getvalue(), "slices.zip", "application/zip", use_container_width=True)
                
        with c2:
            prev = img.resize((int(img.width*z), int(img.height*z))) if z<1 else img.copy()
            draw = ImageDraw.Draw(prev)
            for x in st.session_state.x_cuts: draw.line([(x*z,0),(x*z,prev.height)], fill='red', width=3)
            for y in st.session_state.y_cuts: draw.line([(0,y*z),(prev.width,y*z)], fill='blue', width=3)
            val = streamlit_image_coordinates(prev, key="sl_pad")
            
            if val and val != st.session_state.last_click:
                st.session_state.last_click = val
                click_x, click_y = int(val['x']/z), int(val['y']/z)
                if "添加" in op_mode:
                    if "垂直" in line_type: 
                        if click_x not in st.session_state.x_cuts: 
                            st.session_state.x_cuts.append(click_x)
                            st.session_state.cut_history.append(('x', click_x))
                    else:
                        if click_y not in st.session_state.y_cuts: 
                            st.session_state.y_cuts.append(click_y)
                            st.session_state.cut_history.append(('y', click_y))
                else:
                    if "垂直" in line_type:
                        if st.session_state.x_cuts:
                            closest_x = min(st.session_state.x_cuts, key=lambda x: abs(x - click_x))
                            st.session_state.x_cuts.remove(closest_x)
                            st.session_state.x_cuts.append(click_x)
                            st.toast(f"已移动垂直线")
                    else:
                        if st.session_state.y_cuts:
                            closest_y = min(st.session_state.y_cuts, key=lambda y: abs(y - click_y))
                            st.session_state.y_cuts.remove(closest_y)
                            st.session_state.y_cuts.append(click_y)
                            st.toast(f"已移动水平线")
                st.rerun()

# --- Tab 3: 修复 ---
with tab3:
    st.header("高清修复")
    f = st.file_uploader("上传图片", type=['png','jpg'], key="re_up")
    if f:
        img = clean_image(f)
        with st.expander("参数"):
            up, sh, co = st.checkbox("2倍放大", True), st.slider("锐化",0.0,5.0,2.0), st.slider("对比",0.5,2.0,1.2)
        if st.button("🚀 修复", type="primary"):
            st.session_state['restored_image'] = enhance_image(img, 2.0 if up else 1.0, sh, co)
        if st.session_state['restored_image']:
            res = st.session_state['restored_image']
            st.download_button("📥 下载", convert_image_to_bytes(res), "fixed.png", "image/png", type="primary")
            z = st.slider("对比缩放", 10, 100, 50, key="re_z") / 100.0
            dw, dh = int(res.width*z), int(res.height*z)
            image_comparison(img1=img.resize((dw,dh)), img2=res.resize((dw,dh)), label1="原图", label2="修复", width=dw, show_labels=True, in_memory=True)

# --- Tab 4: 自由框选切割 (防抖动终极版) ---
with tab4:
    st.header("🔳 自由框选切割 (Free Crop)")
    crop_file = st.file_uploader("上传图片", type=['png', 'jpg', 'jpeg', 'webp'], key="crop_uploader")
    
    # 切换图片时重置
    if crop_file and ('crop_filename' not in st.session_state or st.session_state.crop_filename != crop_file.name):
        st.session_state['crop_filename'] = crop_file.name
        st.session_state['canvas_locked'] = False
        st.session_state['locked_scale'] = 1.0
        st.session_state['canvas_key'] = str(uuid.uuid4())
        st.session_state['canvas_bg_json'] = None
        st.session_state['saved_rects'] = [] 
        st.session_state['frozen_drawing'] = None

    if crop_file:
        original_img = clean_image(crop_file)
        w, h = original_img.size
        
        if not st.session_state['canvas_locked']:
            st.info("👇 **第一步：请先拖动滑块，调整到你能看清全图的大小**")
            default_zoom = 50 if w > 1000 else 100
            canvas_zoom = st.slider("🔍 图片缩放 (%)", 10, 100, default_zoom, key="preview_zoom")
            scale_factor = canvas_zoom / 100.0
            display_w = int(w * scale_factor)
            display_h = int(h * scale_factor)
            
            preview_img = original_img.resize((display_w, display_h))
            st.image(preview_img, width=display_w, caption=f"预览效果 ({display_w} x {display_h})")
            
            st.write("---")
            if st.button("🔒 大小合适了，锁定并开始画框", type="primary"):
                st.session_state['canvas_locked'] = True
                st.session_state['locked_scale'] = scale_factor
                st.session_state['canvas_key'] = str(uuid.uuid4())
                
                img_b64 = image_to_base64(preview_img)
                bg_json = {
                    "version": "4.4.0",
                    "objects": [
                        {
                            "type": "image",
                            "version": "4.4.0",
                            "originX": "left", "originY": "top", "left": 0, "top": 0,
                            "width": display_w, "height": display_h,
                            "fill": "rgb(0,0,0)", "stroke": None, "strokeWidth": 0,
                            "scaleX": 1, "scaleY": 1,
                            "opacity": 1, "visible": True, "backgroundColor": "",
                            "src": img_b64,
                            "selectable": False, "evented": False
                        }
                    ]
                }
                st.session_state['canvas_bg_json'] = bg_json
                st.session_state['frozen_drawing'] = bg_json
                st.rerun()

        else:
            c_tools, c_canvas = st.columns([1, 3])
            
            with c_tools:
                st.success("✅ 画板已就绪")
                draw_mode = st.radio("操作模式", ["✏️ 画框模式", "✋ 调整模式"], horizontal=False)
                
                if draw_mode != st.session_state.get('last_draw_mode'):
                    st.session_state['last_draw_mode'] = draw_mode
                    st.session_state['frozen_drawing'] = {
                        "version": "4.4.0",
                        "objects": st.session_state['canvas_bg_json']['objects'] + st.session_state['saved_rects']
                    }
                    st.session_state['canvas_key'] = str(uuid.uuid4())
                    st.rerun()

                st.write("---")
                if st.button("↩️ 撤销上一步", use_container_width=True):
                    if st.session_state['saved_rects']:
                        st.session_state['saved_rects'].pop()
                        st.session_state['frozen_drawing'] = {
                            "version": "4.4.0",
                            "objects": st.session_state['canvas_bg_json']['objects'] + st.session_state['saved_rects']
                        }
                        st.session_state['canvas_key'] = str(uuid.uuid4()) 
                        st.rerun()
                    else:
                        st.toast("没有可以撤销的操作")

                if st.button("🗑️ 清空所有框", use_container_width=True):
                    st.session_state['saved_rects'] = []
                    st.session_state['frozen_drawing'] = st.session_state['canvas_bg_json']
                    st.session_state['canvas_key'] = str(uuid.uuid4())
                    st.rerun()

                st.write("---")
                if st.button("🔄 解锁重置", use_container_width=True):
                    st.session_state['canvas_locked'] = False
                    st.rerun()

            with c_canvas:
                if st.session_state['canvas_bg_json'] is None:
                    st.error("状态丢失，请解锁重试")
                    st.stop()
                    
                bg_w = st.session_state['canvas_bg_json']['objects'][0]['width']
                bg_h = st.session_state['canvas_bg_json']['objects'][0]['height']

                real_mode = "rect" if "画框" in draw_mode else "transform"

                canvas_result = st_canvas(
                    fill_color="rgba(255, 165, 0, 0.3)",
                    stroke_color="#FF0000",
                    stroke_width=2,
                    background_image=None,
                    initial_drawing=st.session_state['frozen_drawing'],
                    update_streamlit=True,
                    height=bg_h,
                    width=bg_w,
                    drawing_mode=real_mode,
                    key=f"canvas_{st.session_state['canvas_key']}",
                    display_toolbar=True
                )

                if canvas_result.json_data is not None:
                    current_objects = [obj for obj in canvas_result.json_data["objects"] if obj["type"] == "rect"]
                    if current_objects != st.session_state['saved_rects']:
                        st.session_state['saved_rects'] = current_objects

            st.divider()
            count = len(st.session_state['saved_rects'])
            st.write(f"当前已选中 **{count}** 个区域")
            
            if count > 0:
                if st.button(f"✂️ 切割并下载这 {count} 张图", type="primary"):
                    zip_buffer = io.BytesIO()
                    with zipfile.ZipFile(zip_buffer, "w") as zf:
                        scale = st.session_state['locked_scale']
                        for i, obj in enumerate(st.session_state['saved_rects']):
                            real_x = int(obj["left"] / scale)
                            real_y = int(obj["top"] / scale)
                            real_w = int((obj["width"] * obj.get("scaleX", 1)) / scale)
                            real_h = int((obj["height"] * obj.get("scaleY", 1)) / scale)
                            
                            if real_w > 0 and real_h > 0:
                                box = (real_x, real_y, real_x+real_w, real_y+real_h)
                                try:
                                    cropped = original_img.crop(box)
                                    img_byte = io.BytesIO()
                                    cropped.save(img_byte, format='PNG')
                                    zf.writestr(f"crop_{i+1}.png", img_byte.getvalue())
                                except: pass
                                    
                    st.download_button("📦 下载ZIP", zip_buffer.getvalue(), "free_crops.zip", "application/zip")

# --- Tab 5: 自由画布/拖拽拼图 ---
with tab5:
    st.header("🎨 自由画布 (Free Canvas)")
    st.markdown("像PPT一样**拖拽、缩放、旋转**图片，自由组合。")
    free_files = st.file_uploader("上传素材图片", type=['png','jpg','jpeg','webp'], accept_multiple_files=True, key="free_canvas_up")
    
    if free_files:
        c1, c2, c3 = st.columns(3)
        cw = c1.number_input("画布宽度", 500, 3000, 800)
        ch = c2.number_input("画布高度", 500, 3000, 600)
        bg = c3.color_picker("画布背景", "#FFFFFF")
        
        if 'canvas_objects' not in st.session_state or st.session_state.get('last_uploaded_files') != free_files:
            initial_json = {"version": "4.4.0", "objects": []}
            for idx, f in enumerate(free_files):
                img = clean_image(f)
                if img.width > 400:
                    ratio = 400 / img.width
                    img = img.resize((400, int(img.height * ratio)))
                img_b64 = image_to_base64(img)
                obj = {
                    "type": "image", "version": "4.4.0", "originX": "left", "originY": "top",
                    "left": 50 + (idx * 30), "top": 50 + (idx * 30),
                    "width": img.width, "height": img.height,
                    "fill": "rgb(0,0,0)", "stroke": None, "strokeWidth": 0,
                    "scaleX": 1, "scaleY": 1, "angle": 0, "flipX": False, "flipY": False,
                    "opacity": 1, "visible": True, "backgroundColor": "",
                    "src": img_b64, "selectable": True, "evented": True
                }
                initial_json["objects"].append(obj)
            st.session_state['canvas_json'] = initial_json
            st.session_state['last_uploaded_files'] = free_files

        canvas_result = st_canvas(
            fill_color=bg, stroke_color="rgba(0, 0, 0, 0)", background_color=bg, background_image=None,
            update_streamlit=True, height=ch, width=cw, drawing_mode="transform",
            initial_drawing=st.session_state['canvas_json'], key="free_canvas_board", display_toolbar=True
        )
        st.caption("提示：点击图片选中，Delete键删除，拖动边框缩放/旋转。")
        
        if canvas_result.image_data is not None:
            result_image = Image.fromarray(canvas_result.image_data.astype('uint8'), 'RGBA')
            st.divider()
            col_d1, col_d2 = st.columns([1, 1])
            with col_d1: st.image(result_image, caption="画布截图", use_column_width=True)
            with col_d2:
                buf = io.BytesIO()
                result_image.save(buf, format="PNG")
                st.download_button("📥 下载设计图", data=buf.getvalue(), file_name="my_design.png", mime="image/png", type="primary")

# --- Tab 6: 标注工具 (最终稳定版) ---
with tab6:
    st.header("📝 图片标注 (Annotation)")
    st.markdown("像微信截图一样添加：**箭头、线条、方框、文字、画笔**。")
    
    anno_file = st.file_uploader("上传图片", type=['png','jpg','jpeg','webp'], key="anno_up")
    
    if anno_file and ('anno_filename' not in st.session_state or st.session_state.anno_filename != anno_file.name):
        st.session_state['anno_filename'] = anno_file.name
        st.session_state['annotate_locked'] = False
        st.session_state['annotate_key'] = str(uuid.uuid4())
        st.session_state['annotate_objects'] = []
        st.session_state['annotate_bg_base64'] = None
        st.session_state['show_anno_result'] = False 

    if anno_file:
        original_img = clean_image(anno_file)
        w, h = original_img.size
        
        if not st.session_state['annotate_locked']:
            st.info("👇 **第一步：调整预览大小（建议让图片完整显示在屏幕内）**")
            default_zoom = 50 if w > 1000 else 100
            zoom = st.slider("🔍 缩放 (%)", 10, 100, default_zoom, key="anno_zoom")
            scale = zoom / 100.0
            dw, dh = int(w * scale), int(h * scale)
            preview = original_img.resize((dw, dh))
            st.image(preview, width=dw, caption=f"画布大小: {dw} x {dh}")
            st.write("---")
            if st.button("🔒 锁定并开始标注", type="primary"):
                st.session_state['annotate_locked'] = True
                st.session_state['annotate_scale'] = scale
                st.session_state['annotate_bg_base64'] = image_to_base64(preview)
                st.session_state['annotate_key'] = str(uuid.uuid4())
                st.rerun()
        else:
            c_tools, c_canvas = st.columns([1, 4])
            
            with c_tools:
                st.success("✅ 开始标注")
                
                tool = st.radio("工具", ["🖌️ 画笔", "➖ 直线/箭头", "🔲 矩形框", "🔴 圆形框", "📝 文字", "✋ 调整/移动"])
                
                stroke_color = st.color_picker("颜色", "#FF0000")
                stroke_width = st.slider("粗细/字号", 1, 50, 3)
                
                if tool == "📝 文字":
                    st.info("提示：点击画布输入文字。")
                
                st.divider()
                
                # [关键修复]：只在点击按钮时刷新Key
                if st.button("↩️ 撤销上一步", use_container_width=True, key="undo_anno"):
                    if st.session_state['annotate_objects']:
                        st.session_state['annotate_objects'].pop()
                        st.session_state['annotate_key'] = str(uuid.uuid4())
                        st.rerun()
                
                if st.button("🗑️ 清空所有", use_container_width=True, key="clear_anno"):
                    st.session_state['annotate_objects'] = []
                    st.session_state['annotate_key'] = str(uuid.uuid4())
                    st.rerun()
                    
                if st.button("🔄 解锁重置", use_container_width=True, key="reset_anno"):
                    st.session_state['annotate_locked'] = False
                    st.session_state['show_anno_result'] = False
                    st.rerun()
                
                st.write("---")
                if st.button("✅ 完成标注 & 生成预览", type="primary", use_container_width=True):
                    st.session_state['show_anno_result'] = True

            with c_canvas:
                mode_map = {
                    "🖌️ 画笔": "freedraw",
                    "➖ 直线/箭头": "line",
                    "🔲 矩形框": "rect",
                    "🔴 圆形框": "circle",
                    "📝 文字": "text",
                    "✋ 调整/移动": "transform"
                }
                real_mode = mode_map[tool]
                
                bg_obj = {
                    "type": "image", "version": "4.4.0", "originX": "left", "originY": "top",
                    "left": 0, "top": 0, "width": int(w * st.session_state['annotate_scale']), 
                    "height": int(h * st.session_state['annotate_scale']),
                    "fill": "rgb(0,0,0)", "stroke": None, "strokeWidth": 0,
                    "scaleX": 1, "scaleY": 1, "opacity": 1, "visible": True, "backgroundColor": "",
                    "src": st.session_state['annotate_bg_base64'],
                    "selectable": False, "evented": False
                }
                
                # [关键修复] 初始数据包含历史对象
                initial_drawing = {
                    "version": "4.4.0",
                    "objects": [bg_obj] + st.session_state['annotate_objects']
                }
                
                # [关键修复] 不再根据 tool 切换 Key，只在撤销时切换
                # 这保证了切换工具时，组件不会销毁，文字工具不会崩溃
                canvas_result = st_canvas(
                    fill_color="rgba(0,0,0,0)", 
                    stroke_color=stroke_color,
                    stroke_width=stroke_width,
                    background_image=None,
                    background_color="#eee",
                    initial_drawing=initial_drawing,
                    update_streamlit=True,
                    height=bg_obj['height'],
                    width=bg_obj['width'],
                    drawing_mode=real_mode,
                    key=f"anno_{st.session_state['annotate_key']}", 
                    display_toolbar=True
                )
                
                # [关键修复] 每次操作完，把除了背景图之外的对象存起来
                if canvas_result.json_data is not None:
                    current_objs = [o for o in canvas_result.json_data["objects"] if o["type"] != "image"]
                    # 只要有变化就存，不管什么模式
                    if current_objs != st.session_state['annotate_objects']:
                         st.session_state['annotate_objects'] = current_objs

            if st.session_state['show_anno_result'] and canvas_result.image_data is not None:
                st.divider()
                st.success("🎉 标注已完成")
                result_img = Image.fromarray(canvas_result.image_data.astype('uint8'), 'RGBA')
                c_d1, c_d2 = st.columns([1, 1])
                with c_d1: st.image(result_img, caption="最终效果")
                with c_d2:
                    buf = io.BytesIO()
                    result_img.save(buf, format="PNG")
                    st.download_button("📥 下载标注后的图片", data=buf.getvalue(), file_name="annotated.png", mime="image/png", type="primary", use_container_width=True)
