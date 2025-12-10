import streamlit as st
import uuid
import os
import math
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
    </style>
""", unsafe_allow_html=True)

# === Session State 初始化 ===
for key in ['x_cuts', 'y_cuts', 'last_click', 'stitched_result', 'restored_image', 'original_for_restore']:
    if key not in st.session_state: st.session_state[key] = None if 'list' not in str(type(st.session_state.get(key))) else []

if 'x_cuts' not in st.session_state: st.session_state['x_cuts'] = []
if 'y_cuts' not in st.session_state: st.session_state['y_cuts'] = []
if 'cut_history' not in st.session_state: st.session_state['cut_history'] = []

if 'canvas_locked' not in st.session_state: st.session_state['canvas_locked'] = False
if 'locked_scale' not in st.session_state: st.session_state['locked_scale'] = 1.0
if 'canvas_key' not in st.session_state: st.session_state['canvas_key'] = "init"

# === 工具函数 ===

def convert_image_to_bytes(img, fmt='PNG'):
    buf = io.BytesIO()
    if fmt.upper() in ['JPEG', 'JPG']: img.save(buf, format=fmt, quality=100, subsampling=0)
    else: img.save(buf, format=fmt)
    return buf.getvalue()

def clean_image(img_file):
    img_file.seek(0)
    image = Image.open(img_file)
    try:
        image = ImageOps.exif_transpose(image)
    except Exception:
        pass
    if image.mode != "RGB":
        image = image.convert("RGB")
    return image

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

def stitch_images_advanced(images, mode='vertical', alignment='max', cols=2, padding=0, bg_color='#FFFFFF'):
    if not images: return None
    bg_color_rgb = tuple(int(bg_color.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))

    if mode == 'vertical':
        max_width = max(img.width for img in images)
        processed_imgs = []
        for img in images:
            if alignment == 'max' and img.width != max_width:
                ratio = max_width / img.width
                new_height = int(img.height * ratio)
                img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
            processed_imgs.append(img)
        total_height = sum(img.height for img in processed_imgs) + (len(processed_imgs) - 1) * padding
        result = Image.new('RGB', (max_width, total_height), bg_color_rgb)
        y_offset = 0
        for img in processed_imgs:
            x_center = (max_width - img.width) // 2
            result.paste(img, (x_center, y_offset))
            y_offset += img.height + padding
            
    elif mode == 'horizontal':
        max_height = max(img.height for img in images)
        processed_imgs = []
        for img in images:
            if alignment == 'max' and img.height != max_height:
                ratio = max_height / img.height
                new_width = int(img.width * ratio)
                img = img.resize((new_width, max_height), Image.Resampling.LANCZOS)
            processed_imgs.append(img)
        total_width = sum(img.width for img in processed_imgs) + (len(processed_imgs) - 1) * padding
        result = Image.new('RGB', (total_width, max_height), bg_color_rgb)
        x_offset = 0
        for img in processed_imgs:
            y_center = (max_height - img.height) // 2
            result.paste(img, (x_offset, y_center))
            x_offset += img.width + padding

    else: 
        target_width = max(img.width for img in images)
        resized_imgs = []
        for img in images:
            ratio = target_width / img.width
            new_h = int(img.height * ratio)
            img = img.resize((target_width, new_h), Image.Resampling.LANCZOS)
            resized_imgs.append(img)
        num_images = len(resized_imgs)
        rows = math.ceil(num_images / cols)
        row_heights = []
        for r in range(rows):
            row_imgs = resized_imgs[r*cols : (r+1)*cols]
            max_h_in_row = max(img.height for img in row_imgs)
            row_heights.append(max_h_in_row)
        total_w = cols * target_width + (cols - 1) * padding
        total_h = sum(row_heights) + (rows - 1) * padding
        result = Image.new('RGB', (total_w, total_h), bg_color_rgb)
        for i, img in enumerate(resized_imgs):
            r = i // cols
            c = i % cols
            x = c * (target_width + padding)
            y = sum(row_heights[:r]) + r * padding
            result.paste(img, (x, y))
            
    return result

# === 主界面 ===
st.title("🛠️ 全能图片工具箱 Pro Max")

tab1, tab2, tab3, tab4 = st.tabs(["🧩 智能拼图", "🔪 参考线切图 (升级版)", "💎 高清修复", "🔳 自由框选切割"])

# --- Tab 1: 拼图 ---
with tab1:
    st.header("图片拼接")
    files = st.file_uploader("上传图片", type=['png','jpg','jpeg','webp'], accept_multiple_files=True, key="stitch_up")
    if files:
        st.markdown("##### 🔢 调整顺序")
        sort_data = []
        cols_ui = st.columns(5)
        for i, f in enumerate(files):
            with cols_ui[i%5]:
                st.image(clean_image(f), use_container_width=True)
                sort_data.append({"f": f, "r": st.number_input(f"No.", 1, value=i+1, key=f"s_{i}", label_visibility="collapsed")})
        sorted_files = [x["f"] for x in sorted(sort_data, key=lambda x: x["r"])]
        st.divider()
        c1, c2, c3 = st.columns([1, 1, 1])
        with c1:
            stitch_mode = st.radio("拼接模式", ['vertical', 'horizontal', 'grid'], format_func=lambda x: "⬇️ 竖向" if x=='vertical' else ("➡️ 横向" if x=='horizontal' else "田 网格"))
        with c2:
            if stitch_mode != 'grid':
                align_mode = st.radio("对齐", ['max', 'original'], format_func=lambda x: "📏 自动对齐" if x=='max' else "🔳 保持原图")
            else:
                grid_cols = st.number_input("列数", 1, 10, 2)
                align_mode = 'max'
        with c3:
            padding = st.slider("间距", 0, 100, 0)
            bg_color = st.color_picker("背景色", "#FFFFFF")

        if st.button("✨ 开始拼接", type="primary", use_container_width=True):
            cols_param = grid_cols if stitch_mode == 'grid' else 1
            st.session_state['stitched_result'] = stitch_images_advanced([clean_image(f) for f in sorted_files], stitch_mode, align_mode, cols_param, padding, bg_color)
            
    if st.session_state['stitched_result']:
        res = st.session_state['stitched_result']
        st.success(f"完成: {res.width}x{res.height}")
        z = st.slider("预览缩放", 10, 100, 50, key="st_zoom")
        st.download_button("📥 下载", convert_image_to_bytes(res), "stitch.png", "image/png", type="primary", use_container_width=True)
        st.image(res.resize((int(res.width*z/100), int(res.height*z/100))) if z<100 else res)

# --- Tab 2: 参考线切图 (新增移动功能) ---
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
            
            # === [新增] 操作模式选择 ===
            st.write("---")
            op_mode = st.radio("操作模式", ["➕ 添加参考线", "✋ 移动/调整参考线"], horizontal=True)
            if op_mode == "✋ 移动/调整参考线":
                st.info("💡 移动模式：点击图片上 **现有的参考线附近**，它会跳到你点击的新位置。")
            
            line_type = st.radio("参考线类型", ["⬇️ 垂直线", "➡️ 水平线"])
            
            st.caption(f"X坐标: {sorted(st.session_state.x_cuts)}")
            st.caption(f"Y坐标: {sorted(st.session_state.y_cuts)}")
            
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
            
            # === [核心逻辑] 点击处理 ===
            if val and val != st.session_state.last_click:
                st.session_state.last_click = val
                click_x, click_y = int(val['x']/z), int(val['y']/z)
                
                # 分支 1: 添加模式
                if "添加" in op_mode:
                    if "垂直" in line_type: 
                        if click_x not in st.session_state.x_cuts: 
                            st.session_state.x_cuts.append(click_x)
                            st.session_state.cut_history.append(('x', click_x))
                    else:
                        if click_y not in st.session_state.y_cuts: 
                            st.session_state.y_cuts.append(click_y)
                            st.session_state.cut_history.append(('y', click_y))
                
                # 分支 2: 移动模式 (新增)
                else:
                    # 逻辑：寻找离点击位置最近的线，把它删掉，然后在点击位置加一条新的
                    if "垂直" in line_type:
                        if st.session_state.x_cuts:
                            # 找最近的 X
                            closest_x = min(st.session_state.x_cuts, key=lambda x: abs(x - click_x))
                            # 移除旧的
                            st.session_state.x_cuts.remove(closest_x)
                            # 添加新的
                            st.session_state.x_cuts.append(click_x)
                            st.toast(f"已将垂直线从 {closest_x} 移动到 {click_x}")
                        else:
                            st.warning("还没有垂直线可以移动")
                    else:
                        if st.session_state.y_cuts:
                            # 找最近的 Y
                            closest_y = min(st.session_state.y_cuts, key=lambda y: abs(y - click_y))
                            st.session_state.y_cuts.remove(closest_y)
                            st.session_state.y_cuts.append(click_y)
                            st.toast(f"已将水平线从 {closest_y} 移动到 {click_y}")
                        else:
                            st.warning("还没有水平线可以移动")

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

# --- Tab 4: 自由框选切割 ---
with tab4:
    st.header("🔳 自由框选切割 (Free Crop)")
    crop_file = st.file_uploader("上传图片", type=['png', 'jpg', 'jpeg', 'webp'], key="crop_uploader")
    
    if crop_file and ('crop_filename' not in st.session_state or st.session_state.crop_filename != crop_file.name):
        st.session_state['crop_filename'] = crop_file.name
        st.session_state['canvas_locked'] = False
        st.session_state['locked_scale'] = 1.0
        st.session_state['canvas_key'] = str(uuid.uuid4())

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
            st.image(preview_img, caption=f"预览效果 ({display_w} x {display_h})")
            st.write("---")
            if st.button("🔒 大小合适了，锁定并开始画框", type="primary"):
                st.session_state['canvas_locked'] = True
                st.session_state['locked_scale'] = scale_factor
                st.session_state['canvas_key'] = str(uuid.uuid4())
                preview_img.save("temp_canvas_bg.png", format="PNG")
                st.rerun()

        else:
            col_c1, col_c2 = st.columns([3, 1])
            with col_c1:
                st.success("✅ **第二步：请在下方直接拖拽画框**")
                if st.button("🔄 重新调整大小 (解锁)"):
                    st.session_state['canvas_locked'] = False
                    st.rerun()
                if os.path.exists("temp_canvas_bg.png"):
                    bg_img_from_disk = Image.open("temp_canvas_bg.png")
                else:
                    st.error("缓存丢失")
                    st.stop()
                canvas_result = st_canvas(
                    fill_color="rgba(255, 165, 0, 0.3)", stroke_color="#FF0000", stroke_width=2,
                    background_image=bg_img_from_disk, update_streamlit=True,
                    height=bg_img_from_disk.height, width=bg_img_from_disk.width,
                    drawing_mode="rect", key=f"canvas_{st.session_state['canvas_key']}", display_toolbar=True
                )
            with col_c2:
                if canvas_result.json_data is not None:
                    objects = canvas_result.json_data["objects"]
                    count = len(objects)
                    st.write(f"选中 {count} 个")
                    if count > 0:
                        if st.button(f"✂️ 执行切割", type="primary"):
                            zip_buffer = io.BytesIO()
                            with zipfile.ZipFile(zip_buffer, "w") as zf:
                                scale = st.session_state['locked_scale']
                                for i, obj in enumerate(objects):
                                    real_x = int(obj["left"] / scale)
                                    real_y = int(obj["top"] / scale)
                                    real_w = int(obj["width"] / scale)
                                    real_h = int(obj["height"] / scale)
                                    if real_w > 0 and real_h > 0:
                                        cropped = original_img.crop((real_x, real_y, real_x+real_w, real_y+real_h))
                                        img_byte = io.BytesIO()
                                        cropped.save(img_byte, format='PNG')
                                        zf.writestr(f"crop_{i+1}.png", img_byte.getvalue())
                            st.download_button("📦 下载ZIP", zip_buffer.getvalue(), "free_crops.zip", "application/zip")
