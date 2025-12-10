import streamlit as st
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter
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
    iframe { border: 1px solid #ddd; } 
    </style>
""", unsafe_allow_html=True)

# === Session State ===
for key in ['x_cuts', 'y_cuts', 'last_click', 'stitched_result', 'restored_image', 'original_for_restore']:
    if key not in st.session_state: st.session_state[key] = None if 'list' not in str(type(st.session_state.get(key))) else []
if 'x_cuts' not in st.session_state: st.session_state['x_cuts'] = []
if 'y_cuts' not in st.session_state: st.session_state['y_cuts'] = []

# === 工具函数 ===
def convert_image_to_bytes(img, fmt='PNG'):
    buf = io.BytesIO()
    if fmt.upper() in ['JPEG', 'JPG']: img.save(buf, format=fmt, quality=100, subsampling=0)
    else: img.save(buf, format=fmt)
    return buf.getvalue()

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

def stitch_images(images, direction='vertical', alignment='max'):
    if not images: return None
    if direction == 'vertical':
        max_dim = max(img.width for img in images)
        imgs = [img.resize((max_dim, int(img.height * (max_dim/img.width))), Image.Resampling.LANCZOS) if alignment == 'max' and img.width != max_dim else img for img in images]
        res = Image.new('RGB', (max_dim, sum(img.height for img in imgs)), (255, 255, 255))
        y = 0
        for i in imgs: res.paste(i, (0, y)); y += i.height
    else:
        max_dim = max(img.height for img in images)
        imgs = [img.resize((int(img.width * (max_dim/img.height)), max_dim), Image.Resampling.LANCZOS) if alignment == 'max' and img.height != max_dim else img for img in images]
        res = Image.new('RGB', (sum(img.width for img in imgs), max_dim), (255, 255, 255))
        x = 0
        for i in imgs: res.paste(i, (x, 0)); x += i.width
    return res

def slice_image_by_guides(img, xs, ys):
    xs = sorted(list(set([0] + xs + [img.width])))
    ys = sorted(list(set([0] + ys + [img.height])))
    return [img.crop((xs[i], ys[j], xs[i+1], ys[j+1])) for j in range(len(ys)-1) for i in range(len(xs)-1) if xs[i+1]>xs[i] and ys[j+1]>ys[j]]

# === 主界面 ===
st.title("🛠️ 全能图片工具箱 Pro Max")

tab1, tab2, tab3, tab4 = st.tabs(["🧩 智能拼图", "🔪 参考线切图", "💎 高清修复", "🔳 自由框选切割"])

# --- Tab 1: 拼图 ---
with tab1:
    st.header("图片拼接")
    files = st.file_uploader("上传图片", type=['png','jpg','jpeg','webp'], accept_multiple_files=True, key="stitch_up")
    if files:
        st.markdown("##### 🔢 调整顺序")
        sort_data = []
        cols = st.columns(5)
        for i, f in enumerate(files):
            with cols[i%5]:
                st.image(Image.open(f), use_container_width=True)
                sort_data.append({"f": f, "r": st.number_input(f"No.", 1, value=i+1, key=f"s_{i}", label_visibility="collapsed")})
        sorted_files = [x["f"] for x in sorted(sort_data, key=lambda x: x["r"])]
        c1, c2 = st.columns(2)
        d = c1.radio("方向", ['vertical', 'horizontal'], format_func=lambda x: "⬇️ 竖向" if x=='vertical' else "➡️ 横向")
        a = c2.radio("对齐", ['max', 'original'], format_func=lambda x: "📏 自动对齐" if x=='max' else "🔳 保持原图")
        if st.button("开始拼接", type="primary"):
            st.session_state['stitched_result'] = stitch_images([Image.open(f) for f in sorted_files], d, a)
            
    if st.session_state['stitched_result']:
        res = st.session_state['stitched_result']
        z = st.slider("预览缩放", 10, 100, 50, key="st_zoom")
        st.download_button("📥 下载大图", convert_image_to_bytes(res), "stitch.png", "image/png", type="primary")
        st.image(res.resize((int(res.width*z/100), int(res.height*z/100))) if z<100 else res)

# --- Tab 2: 参考线切图 ---
with tab2:
    st.header("参考线贯穿切割 (Guillotine)")
    f = st.file_uploader("上传图片", type=['png','jpg','jpeg'], key="sl_up")
    if f:
        img = Image.open(f)
        if 'current_img' not in st.session_state or st.session_state.current_img != f.name:
            st.session_state.x_cuts, st.session_state.y_cuts = [], []
            st.session_state.current_img = f.name
            
        c1, c2 = st.columns([1, 2])
        with c1:
            z = st.slider("缩放", 10, 100, 100, 10, key="sl_z") / 100.0
            mode = st.radio("模式", ["⬇️ 垂直线", "➡️ 水平线"])
            st.caption(f"X: {sorted(st.session_state.x_cuts)}")
            st.caption(f"Y: {sorted(st.session_state.y_cuts)}")
            if st.button("🗑️ 清空"): st.session_state.x_cuts, st.session_state.y_cuts = [], []; st.rerun()
            if st.button("✂️ 切割下载", type="primary"):
                slices = slice_image_by_guides(img, st.session_state.x_cuts, st.session_state.y_cuts)
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w") as zf:
                    for i, s in enumerate(slices):
                        b = io.BytesIO(); s.save(b, 'PNG'); zf.writestr(f"slice_{i+1}.png", b.getvalue())
                st.download_button("📦 下载ZIP", buf.getvalue(), "slices.zip", "application/zip")
        with c2:
            prev = img.resize((int(img.width*z), int(img.height*z))) if z<1 else img.copy()
            draw = ImageDraw.Draw(prev)
            for x in st.session_state.x_cuts: draw.line([(x*z,0),(x*z,prev.height)], fill='red', width=3)
            for y in st.session_state.y_cuts: draw.line([(0,y*z),(prev.width,y*z)], fill='blue', width=3)
            val = streamlit_image_coordinates(prev, key="sl_pad")
            if val and val != st.session_state.last_click:
                st.session_state.last_click = val
                if "垂直" in mode: st.session_state.x_cuts.append(int(val['x']/z))
                else: st.session_state.y_cuts.append(int(val['y']/z))
                st.rerun()

# --- Tab 3: 修复 ---
with tab3:
    st.header("高清修复")
    f = st.file_uploader("上传图片", type=['png','jpg'], key="re_up")
    if f:
        img = Image.open(f).convert("RGB")
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

# --- Tab 4: 自由框选切割 (修复版) ---
with tab4:
    st.header("🔳 自由框选切割 (Free Crop)")
    st.caption("先调整下方滑块缩小图片，然后在图片上拖拽画框。")
    
    crop_file = st.file_uploader("上传图片", type=['png', 'jpg', 'jpeg', 'webp'], key="crop_uploader")
    
    if crop_file:
        original_img = Image.open(crop_file).convert("RGB") # 强制转RGB，防止RGBA导致的显示问题
        w, h = original_img.size
        
        st.write(f"原图尺寸: {w} x {h}")
        
        # === 核心修复：预览缩放滑块 ===
        # 默认缩放到 60% 或者 800px 宽，方便操作
        default_zoom = 50 if w > 1000 else 100
        canvas_zoom = st.slider("🔍 画布缩放 (%) - 调整此项会清空已画的框", 10, 100, default_zoom, key="canvas_zoom")
        
        scale_factor = canvas_zoom / 100.0
        
        # 计算显示尺寸
        display_w = int(w * scale_factor)
        display_h = int(h * scale_factor)
        
        # 实时生成一张缩略图用于显示（这解决了图片不显示的问题）
        # 并且将 canvas 的宽高严格锁定为这张图的宽高
        display_img = original_img.resize((display_w, display_h))

        col_c1, col_c2 = st.columns([3, 1])
        
        with col_c1:
            st.write("👇 **在下方拖拽画框：**")
            # 绘图组件
            canvas_result = st_canvas(
                fill_color="rgba(255, 165, 0, 0.3)",
                stroke_color="#FF0000",
                stroke_width=2,
                background_image=display_img, # 使用缩放后的图
                update_streamlit=True,
                height=display_h, # 严格匹配高度
                width=display_w,  # 严格匹配宽度
                drawing_mode="rect",
                key="canvas_cropper",
                display_toolbar=True
            )

        with col_c2:
            st.info("💡 操作指南：")
            st.markdown("""
            1. **调整上方滑块**让图片完全显示。
            2. 鼠标左键**拖拽画框**。
            3. 支持画**多个框**。
            4. 点击右侧按钮批量下载。
            """)
            
            if canvas_result.json_data is not None:
                objects = canvas_result.json_data["objects"]
                count = len(objects)
                st.write(f"已选中 **{count}** 个")
                
                if count > 0:
                    if st.button(f"✂️ 切割并下载", type="primary"):
                        zip_buffer = io.BytesIO()
                        with zipfile.ZipFile(zip_buffer, "w") as zf:
                            for i, obj in enumerate(objects):
                                # 核心逻辑：将画布坐标还原回原图坐标
                                # 必须除以 scale_factor
                                real_x = int(obj["left"] / scale_factor)
                                real_y = int(obj["top"] / scale_factor)
                                real_w = int(obj["width"] / scale_factor)
                                real_h = int(obj["height"] / scale_factor)
                                
                                box = (real_x, real_y, real_x + real_w, real_y + real_h)
                                
                                if real_w > 0 and real_h > 0:
                                    cropped = original_img.crop(box)
                                    img_byte = io.BytesIO()
                                    cropped.save(img_byte, format='PNG')
                                    zf.writestr(f"crop_{i+1}.png", img_byte.getvalue())
                        
                        st.download_button("📦 下载ZIP", zip_buffer.getvalue(), "free_crops.zip", "application/zip")
                        st.success("完成！")
