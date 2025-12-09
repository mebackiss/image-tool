import streamlit as st
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter
import io
import zipfile
from streamlit_image_coordinates import streamlit_image_coordinates
# [新增] 引入对比组件
from streamlit_image_comparison import image_comparison

# === 页面配置 ===
st.set_page_config(page_title="图片工具箱 Pro", layout="wide", page_icon="✨")

# 防止大图报错
Image.MAX_IMAGE_PIXELS = None

# === CSS 样式优化 ===
st.markdown("""
    <style>
    .stTabs [data-baseweb="tab-list"] { gap: 24px; }
    .stTabs [data-baseweb="tab"] { height: 50px; white-space: pre-wrap; background-color: #f0f2f6; border-radius: 4px 4px 0 0; gap: 1px; padding-top: 10px; padding-bottom: 10px; }
    .stTabs [aria-selected="true"] { background-color: #ffffff; border-top: 2px solid #ff4b4b; }
    </style>
""", unsafe_allow_html=True)

# === Session State 初始化 ===
if 'x_cuts' not in st.session_state: st.session_state['x_cuts'] = []
if 'y_cuts' not in st.session_state: st.session_state['y_cuts'] = []
if 'last_click' not in st.session_state: st.session_state['last_click'] = None
if 'stitched_result' not in st.session_state: st.session_state['stitched_result'] = None
if 'restored_image' not in st.session_state: st.session_state['restored_image'] = None
if 'original_for_restore' not in st.session_state: st.session_state['original_for_restore'] = None

# === 核心工具函数 ===

def convert_image_to_bytes(img, fmt='PNG'):
    buf = io.BytesIO()
    if fmt.upper() in ['JPEG', 'JPG']:
        img.save(buf, format=fmt, quality=100, subsampling=0)
    else:
        img.save(buf, format=fmt)
    return buf.getvalue()

def enhance_image(image, upscale_factor=2.0, sharpness=2.0, contrast=1.1, color=1.1):
    if upscale_factor > 1.0:
        new_w = int(image.width * upscale_factor)
        new_h = int(image.height * upscale_factor)
        img = image.resize((new_w, new_h), Image.Resampling.LANCZOS)
    else:
        img = image.copy()
    
    img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3))
    enhancer_contrast = ImageEnhance.Contrast(img)
    img = enhancer_contrast.enhance(contrast)
    enhancer_color = ImageEnhance.Color(img)
    img = enhancer_color.enhance(color)
    enhancer_sharp = ImageEnhance.Sharpness(img)
    img = enhancer_sharp.enhance(sharpness)
    
    return img

def stitch_images(images, direction='vertical', alignment='max'):
    if not images: return None
    if direction == 'vertical':
        max_width = max(img.width for img in images)
        processed_imgs = []
        for img in images:
            if alignment == 'max' and img.width != max_width:
                ratio = max_width / img.width
                new_height = int(img.height * ratio)
                img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
            processed_imgs.append(img)
        total_height = sum(img.height for img in processed_imgs)
        result = Image.new('RGB', (max_width, total_height), (255, 255, 255))
        y_offset = 0
        for img in processed_imgs:
            result.paste(img, (0, y_offset))
            y_offset += img.height
    else:
        max_height = max(img.height for img in images)
        processed_imgs = []
        for img in images:
            if alignment == 'max' and img.height != max_height:
                ratio = max_height / img.height
                new_width = int(img.width * ratio)
                img = img.resize((new_width, max_height), Image.Resampling.LANCZOS)
            processed_imgs.append(img)
        total_width = sum(img.width for img in processed_imgs)
        result = Image.new('RGB', (total_width, max_height), (255, 255, 255))
        x_offset = 0
        for img in processed_imgs:
            result.paste(img, (x_offset, 0))
            x_offset += img.width
    return result

def slice_image_by_guides(img, x_guides, y_guides):
    xs = sorted(list(set([0] + x_guides + [img.width])))
    ys = sorted(list(set([0] + y_guides + [img.height])))
    slices = []
    for j in range(len(ys) - 1):
        for i in range(len(xs) - 1):
            box = (xs[i], ys[j], xs[i+1], ys[j+1])
            if box[2] > box[0] and box[3] > box[1]:
                crop = img.crop(box)
                slices.append(crop)
    return slices

# === 界面部分 ===

st.title("✨ 超级图片工具箱 Pro")

tab1, tab2, tab3 = st.tabs(["🧩 智能拼图", "🔪 精准切图", "💎 高清修复 (拖拽对比)"])

# === Tab 1: 拼图 ===
with tab1:
    st.header("图片拼接")
    uploaded_files = st.file_uploader("上传图片", type=['png', 'jpg', 'jpeg', 'webp'], accept_multiple_files=True, key="stitch_up")
    
    if not uploaded_files: st.session_state['stitched_result'] = None
    sorted_files = []

    if uploaded_files:
        st.markdown("##### 🔢 顺序调整")
        sort_data = []
        cols = st.columns(5)
        for idx, file in enumerate(uploaded_files):
            with cols[idx % 5]:
                st.image(Image.open(file), use_container_width=True)
                rank = st.number_input(f"No.", 1, value=idx+1, key=f"s_{idx}", label_visibility="collapsed")
                sort_data.append({"f": file, "r": rank})
        sorted_files = [x["f"] for x in sorted(sort_data, key=lambda x: x["r"])]
        st.divider()

    c1, c2 = st.columns(2)
    with c1: d = st.radio("方向", ['vertical', 'horizontal'], format_func=lambda x: "⬇️ 竖向" if x == 'vertical' else "➡️ 横向")
    with c2: a = st.radio("对齐", ['max', 'original'], format_func=lambda x: "📏 自动对齐" if x == 'max' else "🔳 保持原图")
    
    if sorted_files and st.button("开始拼接", type="primary"):
        with st.spinner("处理中..."):
            st.session_state['stitched_result'] = stitch_images([Image.open(f) for f in sorted_files], d, a)

    if st.session_state['stitched_result']:
        res = st.session_state['stitched_result']
        zoom = st.slider("🔍 预览缩放", 10, 100, 50, key="st_zoom")
        st.download_button("📥 下载", convert_image_to_bytes(res), "stitch.png", "image/png", type="primary")
        
        if zoom < 100:
            st.image(res.resize((int(res.width*zoom/100), int(res.height*zoom/100))), caption=f"预览 {zoom}%")
        else:
            st.image(res)

# === Tab 2: 切图 ===
with tab2:
    st.header("参考线切图")
    slice_file = st.file_uploader("上传图片", type=['png', 'jpg', 'jpeg', 'webp'], key="slice_up")
    
    if slice_file:
        if 'current_img_name' not in st.session_state or st.session_state.current_img_name != slice_file.name:
            st.session_state.x_cuts = []
            st.session_state.y_cuts = []
            st.session_state.current_img_name = slice_file.name
        
        orig_img = Image.open(slice_file)
        w, h = orig_img.size
        
        col_t, col_v = st.columns([1, 2])
        with col_t:
            st.info("点击图片添加参考线")
            zoom = st.slider("🔍 预览缩放 (%)", 10, 100, 100, step=10, key="sl_zoom")
            zoom_ratio = zoom / 100.0
            mode = st.radio("模式", ["⬇️ 垂直线", "➡️ 水平线"])
            
            x_s = st.text_input("X坐标", value=",".join(map(str, sorted(st.session_state.x_cuts))))
            y_s = st.text_input("Y坐标", value=",".join(map(str, sorted(st.session_state.y_cuts))))
            
            try:
                if x_s: st.session_state.x_cuts = [int(x) for x in x_s.replace('，',',').split(',') if x.strip()]
                else: st.session_state.x_cuts = []
                if y_s: st.session_state.y_cuts = [int(y) for y in y_s.replace('，',',').split(',') if y.strip()]
                else: st.session_state.y_cuts = []
            except: pass

            if st.button("🗑️ 清空"):
                st.session_state.x_cuts = []
                st.session_state.y_cuts = []
                st.rerun()
            
            if st.button("✂️ 切割下载", type="primary"):
                slices = slice_image_by_guides(orig_img, st.session_state.x_cuts, st.session_state.y_cuts)
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w") as zf:
                    for i, s in enumerate(slices):
                        b = io.BytesIO()
                        s.save(b, 'PNG')
                        zf.writestr(f"slice_{i+1}.png", b.getvalue())
                st.download_button("📦 下载ZIP", buf.getvalue(), "slices.zip", "application/zip")

        with col_v:
            d_w, d_h = int(w * zoom_ratio), int(h * zoom_ratio)
            prev = orig_img.resize((d_w, d_h)) if zoom < 100 else orig_img.copy()
            draw = ImageDraw.Draw(prev)
            for x in st.session_state.x_cuts:
                dx = int(x * zoom_ratio)
                draw.line([(dx, 0), (dx, d_h)], fill='red', width=3)
            for y in st.session_state.y_cuts:
                dy = int(y * zoom_ratio)
                draw.line([(0, dy), (d_w, dy)], fill='blue', width=3)
            
            val = streamlit_image_coordinates(prev, key="slice_pad")
            if val and val != st.session_state.last_click:
                st.session_state.last_click = val
                rx, ry = int(val['x']/zoom_ratio), int(val['y']/zoom_ratio)
                if "垂直" in mode: 
                    if rx not in st.session_state.x_cuts: st.session_state.x_cuts.append(rx)
                else:
                    if ry not in st.session_state.y_cuts: st.session_state.y_cuts.append(ry)
                st.rerun()

# === Tab 3: 修复 (核心修改) ===
with tab3:
    st.header("💎 图片高清修复")
    st.caption("上传图片 -> 设置参数 -> 点击修复 -> 拖动中间的竖线查看效果")
    
    restore_file = st.file_uploader("上传图片", type=['png', 'jpg', 'jpeg', 'webp'], key="res_up")
    
    if restore_file and ('restore_filename' not in st.session_state or st.session_state.restore_filename != restore_file.name):
        st.session_state['restored_image'] = None
        st.session_state['original_for_restore'] = Image.open(restore_file).convert("RGB")
        st.session_state['restore_filename'] = restore_file.name

    if st.session_state['original_for_restore']:
        orig_img = st.session_state['original_for_restore']
        
        with st.expander("⚙️ 增强参数 (可选)", expanded=False):
            c1, c2, c3 = st.columns(3)
            upscale = c1.checkbox("2倍放大", value=True)
            sharp = c2.slider("锐化", 0.0, 5.0, 2.0, 0.1)
            contrast = c3.slider("对比度", 0.5, 2.0, 1.2, 0.1)
        
        if st.button("🚀 开始修复", type="primary"):
            with st.spinner("修复中..."):
                factor = 2.0 if upscale else 1.0
                st.session_state['restored_image'] = enhance_image(orig_img, factor, sharp, contrast)
        
        # --- 结果展示区 ---
        if st.session_state['restored_image']:
            res_img = st.session_state['restored_image']
            
            st.divider()
            
            # 1. 下载按钮
            st.download_button(
                "📥 下载修复后的高清大图", 
                convert_image_to_bytes(res_img), 
                "restored_hd.png", 
                "image/png", 
                type="primary"
            )

            st.write("---")
            
            # 2. 预览缩放滑块 (解决预览图过大的问题)
            # 用户想要"缩小"，所以我们提供 10% - 100% 的滑块
            compare_zoom = st.slider("🔍 对比预览图缩放 (%)", 10, 100, 50, key="compare_zoom")
            
            # 3. 准备对比图
            # 为了在网页上流畅对比，我们需要把两张图都缩放到用户指定的比例
            # 注意：这只是为了"显示"，不影响下载
            
            display_w = int(res_img.width * compare_zoom / 100)
            display_h = int(res_img.height * compare_zoom / 100)
            
            # 原始图也要先放大到和修复图一样大（如果修复图做了2倍放大的话），然后再整体缩小显示
            # 这样两张图才能完全重合对比
            img1_for_display = orig_img.resize((display_w, display_h), Image.Resampling.LANCZOS)
            img2_for_display = res_img.resize((display_w, display_h), Image.Resampling.LANCZOS)
            
            st.caption("↔️ 左右拖动中间的滑杆来查看【修复前 vs 修复后】")
            
            # 4. 调用对比组件
            image_comparison(
                img1=img1_for_display,
                img2=img2_for_display,
                label1="修复前 (原图)",
                label2="修复后 (高清)",
                width=display_w, # 设置组件宽度
                show_labels=True,
                make_responsive=True, # 自适应宽度
                in_memory=True # 告诉组件这是PIL对象不是路径
            )