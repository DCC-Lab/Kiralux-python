from PIL import Image
src = r"C:\Mac\Home\ThorImageRE\tools\desktop_grab.png"
dst = r"C:\Mac\Home\ThorImageRE\tools\desktop_grab_small.png"
im = Image.open(src)
im.thumbnail((1400, 1400), Image.LANCZOS)
im.save(dst)
print("saved", dst, im.size)
