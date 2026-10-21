import base64, io
from PIL import Image
im = Image.open(r"C:\Mac\Home\ThorImageRE\tools\camera_frame.png")
im.thumbnail((360, 360), Image.LANCZOS)
buf = io.BytesIO()
im.convert("L").save(buf, format="JPEG", quality=72)
b64 = base64.b64encode(buf.getvalue()).decode()
open(r"C:\Mac\Home\ThorImageRE\tools\frame_datauri.txt", "w").write("data:image/jpeg;base64," + b64)
print("ok", len(b64), "chars", im.size)
