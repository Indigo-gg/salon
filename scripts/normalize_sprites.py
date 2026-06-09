import os
import shutil
from PIL import Image

SPRITES_DIR = r"D:\Pcode\play\agent-team\web\frontend\src\assets\images\sprites"
BACKUP_DIR = r"D:\Pcode\play\agent-team\web\frontend\src\assets\images\sprites_backup"
TARGET_HEIGHT = 120
FRAME_WIDTH = 140
FRAME_HEIGHT = 140
ROWS = 3
COLS = 4

def get_true_bbox(im):
    # Returns bounding box of non-zero alpha
    if im.mode in ('RGBA', 'LA'):
        alpha = im.split()[-1]
        return alpha.getbbox()
    return im.getbbox()

def process_sprites():
    for filename in os.listdir(BACKUP_DIR):
        if not filename.endswith('.png'):
            continue
            
        backup_path = os.path.join(BACKUP_DIR, filename)
        target_path = os.path.join(SPRITES_DIR, filename)
        
        img = Image.open(backup_path).convert('RGBA')
        
        # 1. Find the maximum height of the character across all frames in this sprite
        max_char_height = 0
        frames_bboxes = []
        
        for r in range(ROWS):
            for c in range(COLS):
                x0, y0 = c * FRAME_WIDTH, r * FRAME_HEIGHT
                frame = img.crop((x0, y0, x0 + FRAME_WIDTH, y0 + FRAME_HEIGHT))
                bbox = get_true_bbox(frame)
                frames_bboxes.append((frame, bbox))
                
                if bbox:
                    h = bbox[3] - bbox[1]
                    if h > max_char_height:
                        max_char_height = h
                        
        if max_char_height == 0:
            continue
            
        scale_factor = TARGET_HEIGHT / max_char_height
        
        new_sprite = Image.new('RGBA', (COLS * FRAME_WIDTH, ROWS * FRAME_HEIGHT), (0, 0, 0, 0))
        
        idx = 0
        for r in range(ROWS):
            for c in range(COLS):
                frame, bbox = frames_bboxes[idx]
                idx += 1
                
                new_frame = Image.new('RGBA', (FRAME_WIDTH, FRAME_HEIGHT), (0, 0, 0, 0))
                
                if bbox:
                    # Extract just the character
                    char_img = frame.crop(bbox)
                    char_w = bbox[2] - bbox[0]
                    char_h = bbox[3] - bbox[1]
                    
                    # Scale character
                    new_w = int(char_w * scale_factor)
                    new_h = int(char_h * scale_factor)
                    
                    if new_w > 0 and new_h > 0:
                        scaled_char = char_img.resize((new_w, new_h), Image.NEAREST)
                        
                        # Ensure we crop exactly to the non-transparent pixels after resize
                        scaled_bbox = get_true_bbox(scaled_char)
                        if scaled_bbox:
                            scaled_char = scaled_char.crop(scaled_bbox)
                            final_w = scaled_bbox[2] - scaled_bbox[0]
                            final_h = scaled_bbox[3] - scaled_bbox[1]
                        else:
                            final_w, final_h = new_w, new_h
                            
                        # Calculate position: horizontal center, bottom aligned
                        paste_x = (FRAME_WIDTH - final_w) // 2
                        paste_y = FRAME_HEIGHT - final_h
                        
                        new_frame.paste(scaled_char, (paste_x, paste_y))
                
                new_sprite.paste(new_frame, (c * FRAME_WIDTH, r * FRAME_HEIGHT))
                
        new_sprite.save(target_path)
        print(f"Saved normalized {filename}")

if __name__ == "__main__":
    process_sprites()
