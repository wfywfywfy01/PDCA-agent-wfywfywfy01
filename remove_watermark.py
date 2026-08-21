"""
去除图片中重复平铺的半透明文字水印。
思路：水印文字为灰色半透明，通过检测灰度像素范围并做修复（inpaint）填充。
"""
import cv2
import numpy as np
from PIL import Image


def remove_watermark(input_path: str, output_path: str) -> None:
    img = cv2.imdecode(np.fromfile(input_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    # --- 1. 深色背景区域的水印：低饱和灰色，中等亮度 ---
    mask_dark = cv2.inRange(hsv, np.array([0, 0, 50]), np.array([180, 55, 145]))

    # --- 2. 橙色卡片区域的水印：水印文字比橙色背景饱和度低，亮度偏高 ---
    # 橙色卡片背景 H≈15-25, S>100, V>150；水印在其上呈现为 S<80 的灰橙色
    mask_orange_wm = cv2.inRange(hsv, np.array([0, 0, 140]), np.array([180, 80, 220]))

    # 仅在橙色卡片范围内启用橙色水印 mask（避免误伤绿色气泡的高亮边缘）
    orange_region = cv2.inRange(hsv, np.array([10, 80, 130]), np.array([30, 255, 255]))
    orange_region_dilated = cv2.dilate(orange_region, np.ones((20, 20), np.uint8), iterations=3)
    mask_orange_wm = cv2.bitwise_and(mask_orange_wm, orange_region_dilated)

    # 合并两个 mask
    mask = cv2.bitwise_or(mask_dark, mask_orange_wm)

    # 膨胀覆盖文字边缘毛刺
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask = cv2.dilate(mask, kernel, iterations=2)

    # Telea 算法修复
    result = cv2.inpaint(img, mask, inpaintRadius=8, flags=cv2.INPAINT_TELEA)

    # 保存结果
    ext = output_path.rsplit(".", 1)[-1].lower()
    success, buf = cv2.imencode(f".{ext}", result)
    if success:
        buf.tofile(output_path)
        print(f"已保存：{output_path}")
    else:
        print("编码失败")


if __name__ == "__main__":
    input_file = r"C:\Users\frank\.cursor\projects\d-PDCA\assets\c__Users_frank_AppData_Roaming_Cursor_User_workspaceStorage_empty-window_images_download-05ffe5d2-2c09-4775-aaab-b004023aee4b.png"
    output_file = r"D:\经销商PDCA\assets\no_watermark.png"
    remove_watermark(input_file, output_file)
