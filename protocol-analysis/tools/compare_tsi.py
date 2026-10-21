import numpy as np
from PIL import Image

# TSI Windows image (decoded correctly by the SDK) -- already 8-bit stretched
tsi = np.array(Image.open("/Users/dccote/ThorImageRE/tools/camera_frame.png").convert("L"))
print("TSI image", tsi.shape)
# crop smooth area, zoom
cy, cx = 1000, 1200
crop = tsi[cy:cy+120, cx:cx+160]
Image.fromarray(crop).resize((160*4, 120*4), Image.NEAREST).save("tsi_crop.png")
print("TSI crop std =", crop.std())
# vertical/horizontal profile of the crop
print("TSI vmed =", np.median(np.abs(np.diff(crop.astype(int), axis=0))),
      "hmed =", np.median(np.abs(np.diff(crop.astype(int), axis=1))))
