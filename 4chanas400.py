import asyncio
import httpx
import json
import sys
import textwrap
import re
import os
import io
import qrcode
import tempfile
import subprocess
from PIL import Image
from telnetlib3 import create_server

# ==============================================================================
# CONFIGURATION MODULE
# ==============================================================================
TELNET_PORT = 2324
TERMINAL_COLS = 78
SZ_BINARY_PATH = r"M:\BBSTELNETWEB\sz.exe"

# ==============================================================================
# IBM 5250 SCREEN MANAGEMENT UTILITIES
# ==============================================================================
def draw_as400_header(writer, title="MAIN MENU", current_board="", page_num=1):
    """Renders a static IBM AS/400 system header matrix with page tracking."""
    writer.write("\x1b[2J\x1b[H")
    
    board_suffix = f"     Board: /{current_board}/" if current_board else ""
    page_suffix = f"Page: {page_num:02d}" if current_board else "       "
    
    writer.write(f"\x1b[1;32mSYS-400      4CHAN IMAGEBOARD ENGINE{board_suffix}\x1b[0m")
    writer.write(f"\x1b[1;32m{' '*(TERMINAL_COLS-76-len(board_suffix))}{page_suffix}  AS/400 V4R5\x1b[0m\r\n")
    
    padding = (TERMINAL_COLS - len(title)) // 2
    writer.write(f"{' ' * padding}\x1b[1;37m{title}\x1b[0m\r\n")
    writer.write("\x1b[1;34m" + "=" * TERMINAL_COLS + "\x1b[0m\r\n\r\n")

def draw_as400_footer(writer, has_more=False):
    """Draws a fixed command menu bar with directional scrolling hints."""
    writer.write("\x1b[21;1H")
    writer.write("\x1b[1;34m" + "-" * TERMINAL_COLS + "\x1b[0m\r\n")
    
    scroll_hints = "More..." if has_more else "Bottom "
    writer.write(f" F3=Exit   F12=Cancel   +=Next Page   -=Prev Page                 \x1b[1;37m{scroll_hints}\x1b[0m\r\n")
    writer.write("\x1b[1;32mSelection or command\x1b[0m\r\n")
    writer.write("\x1b[1;37m===> \x1b[0m")

def clean_html_remnants(text):
    """Strips 4chan HTML structures cleanly."""
    if not text:
        return ""
    text = text.replace("<br>", "\n").replace("</br>", "\n")
    text = text.replace("&gt;", ">").replace("&lt;", "<").replace("&quot;", '"').replace("&#039;", "'")
    text = re.sub(r'<[^>]+>', '', text)
    return text.strip()

# ==============================================================================
# PURE PYTHON SCREEN RENDERING ENGINES
# ==============================================================================
async def render_catalog_pure_python(threads_data, writer):
    """Maps catalog data objects into aligned screen rows."""
    current_row = 5
    for idx, thread in enumerate(threads_data):
        if current_row >= 20: break
            
        display_num = idx + 1
        subject = thread.get('sub', '')
        comment_snippet = clean_html_remnants(thread.get('com', ''))
        
        if not subject:
            subject = comment_snippet[:120].replace("\n", " ")
        if not subject:
            subject = "[No Subject Context]"
            
        img_flag = " *IMG " if thread.get('filename') else "      "
        replies = thread.get('replies', 0)
        meta_trailer = f" (Replies: {replies})"
        
        max_title_w = (TERMINAL_COLS - 23) - len(meta_trailer)
        wrapped_title = textwrap.wrap(subject, width=max_title_w)
        
        if wrapped_title:
            wrapped_title[0] += meta_trailer
        else:
            wrapped_title = [meta_trailer]

        for i, line in enumerate(wrapped_title):
            if current_row >= 20: break
            writer.write(f"\x1b[{current_row};1H\x1b[K")
            if i == 0:
                writer.write(f"\x1b[1;32mOption {display_num:02d}\x1b[1;36m{img_flag}\x1b[1;37m. . : {line}\x1b[0m")
            else:
                writer.write(f"                       \x1b[1;37m{line}\x1b[0m")
            current_row += 1
    await writer.drain()

def generate_thread_line_buffer(posts):
    """Pre-wraps the entire thread into exact ANSI screen lines."""
    lines_buffer = []
    
    for idx, post in enumerate(posts):
        comment = clean_html_remnants(post.get('com', ''))
        p_id = post.get('no')
        
        header_text = f"ORIGINAL POST (OP) No.{p_id}:" if idx == 0 else f"REPLY No.{p_id}:"
        
        current_img_target = None
        if post.get('tim'):
            ext = post.get('ext', '')
            raw_url = f"https://i.4cdn.org/IMAGE_BOARD_PLACEHOLDER/{post.get('tim')}{ext}"
            
            if ext.lower() in ('.webm', '.mp4', '.gif'):
                thumb_url = f"https://i.4cdn.org/IMAGE_BOARD_PLACEHOLDER/{post.get('tim')}s.jpg"
            else:
                thumb_url = raw_url
                
            header_text += f"  \x1b[1;36m[IMAGE_PLACEHOLDER]\x1b[0m"
            current_img_target = {"url_template": raw_url, "thumb_template": thumb_url}

        lines_buffer.append({"text": header_text, "is_header": True, "img": current_img_target})
        
        if not comment:
            comment = "[Image / No Content Text]"
            
        for segment in comment.split('\n'):
            if segment.strip():
                for line in textwrap.wrap(segment, width=TERMINAL_COLS):
                    lines_buffer.append({"text": f"\x1b[1;32m{line}\x1b[0m", "is_header": False, "img": None})
            else:
                lines_buffer.append({"text": "", "is_header": False, "img": None})
                
        lines_buffer.append({"text": "\x1b[1;34m" + "." * TERMINAL_COLS + "\x1b[0m", "is_header": False, "img": None})
        
    return lines_buffer

# ==============================================================================
# CO-LOCATED IMAGE ARTIFACT & QR GENERATION ENGINE
# ==============================================================================
async def render_split_media_pane(img_struct, board, writer, start_row=6):
    """Pipes an expanded aspect-ratio-locked TrueColor thumbnail on the left and balanced QR code."""
    thumb_lines = []
    
    raw_asset_target = img_struct["url_template"].replace("IMAGE_BOARD_PLACEHOLDER", board)
    thumb_asset_target = img_struct["thumb_template"].replace("IMAGE_BOARD_PLACEHOLDER", board)
    
    try:
        headers = {"User-Agent": "IBM-5250-Workstation-Proxy/4.0"}
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            img_response = await client.get(thumb_asset_target, headers=headers)
            
        if img_response.status_code == 200:
            pil_img = Image.open(io.BytesIO(img_response.content)).convert('RGB')
            orig_w, orig_h = pil_img.size
            
            # Max boundary sizing boosted to 29 pixels high
            max_w, max_h = 30, 29
            
            # Calculate scaling matrix using the longest constraining edge
            scale = min(max_w / orig_w, max_h / orig_h)
            new_w = int(orig_w * scale)
            new_h = int(orig_h * scale)
            
            # Bound rules: minimum 2x2 grid and force even heights for half-block terminal sizing
            new_w = max(2, new_w)
            new_h = max(2, (new_h // 2) * 2) 
            
            pil_img = pil_img.resize((new_w, new_h), Image.Resampling.NEAREST)
            pixels = pil_img.load()
            
            # Calculate center alignments to prevent middle gutter wobble
            left_pad = (30 - new_w) // 2
            right_pad = 30 - new_w - left_pad
            
            for y in range(0, new_h, 2):
                line_str = " " * left_pad
                for x in range(new_w):
                    r1, g1, b1 = pixels[x, y]
                    r2, g2, b2 = pixels[x, y+1]
                    line_str += f"\x1b[38;2;{r1};{g1};{b1}m\x1b[48;2;{r2};{g2};{b2}m▀"
                line_str += "\x1b[0m" + (" " * right_pad)
                thumb_lines.append(line_str)
    except:
        pass

    # Pad terminal vertical rows up to max half-block matrix limits (~15 screen rows)
    while len(thumb_lines) < 15:
        thumb_lines.append(" " * 30)

    clean_url = raw_asset_target.replace("https://", "").replace("www.", "")
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=1, border=1)
    qr.add_data(clean_url)
    qr.make(fit=True)
    qr_matrix = qr.get_matrix()
    
    qr_lines = []
    for r_idx in range(0, len(qr_matrix), 2):
        row1 = qr_matrix[r_idx]
        row2 = qr_matrix[r_idx+1] if (r_idx + 1) < len(qr_matrix) else [False] * len(row1)
        
        line_str = "\x1b[47;30m" 
        for c_idx in range(len(row1)):
            top_pixel = row1[c_idx]
            bottom_pixel = row2[c_idx]
            
            if top_pixel and bottom_pixel: line_str += " "
            elif top_pixel and not bottom_pixel: line_str += "▄"
            elif not top_pixel and bottom_pixel: line_str += "▀"
            else: line_str += "█"
        line_str += "\x1b[0m"
        qr_lines.append(line_str)

    current_row = start_row
    for clear_row in range(start_row, 21):
        writer.write(f"\x1b[{clear_row};1H\x1b[K")
        
    max_lines = max(len(thumb_lines), len(qr_lines))
    
    for i in range(max_lines):
        if current_row >= 21: break
        
        t_part = thumb_lines[i] if i < len(thumb_lines) else " " * 30
        q_part = qr_lines[i] if i < len(qr_lines) else ""
        
        full_row = " " * 4 + t_part + " " * 6 + q_part
        writer.write(f"\x1b[{current_row};1H{full_row}")
        current_row += 1

# ==============================================================================
# 4CHAN RAW NETWORKING TRANSLATION CORE
# ==============================================================================
async def fetch_board_catalog(board_name, target_page=1):
    try:
        url = f"https://a.4cdn.org/{board_name}/catalog.json"
        headers = {"User-Agent": "IBM-5250-Workstation-Proxy/4.0"}
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as http_client:
            response = await http_client.get(url, headers=headers)
            
        if response.status_code == 200:
            catalog_data = response.json()
            all_threads = []
            for page in catalog_data:
                for thread in page.get('threads', []):
                    all_threads.append(thread)
            
            start_idx = (target_page - 1) * 10
            end_idx = start_idx + 10
            page_threads = all_threads[start_idx:end_idx]
            has_more = len(all_threads) > end_idx
            
            threads_map = {}
            for idx, thread in enumerate(page_threads):
                img_struct = None
                if thread.get('tim'):
                    ext = thread.get('ext', '')
                    raw_url = f"https://i.4cdn.org/IMAGE_BOARD_PLACEHOLDER/{thread.get('tim')}{ext}"
                    
                    if ext.lower() in ('.webm', '.mp4', '.gif'):
                        thumb_url = f"https://i.4cdn.org/IMAGE_BOARD_PLACEHOLDER/{thread.get('tim')}s.jpg"
                    else:
                        thumb_url = raw_url
                        
                    img_struct = {"url_template": raw_url, "thumb_template": thumb_url}
                threads_map[str(idx + 1)] = {"id": str(thread.get('no')), "board": board_name, "img": img_struct}
                
            return page_threads, threads_map, has_more
        return None, {}, False
    except:
        return None, {}, False

async def fetch_full_thread(board_name, thread_id):
    try:
        url = f"https://a.4cdn.org/{board_name}/thread/{thread_id}.json"
        headers = {"User-Agent": "IBM-5250-Workstation-Proxy/4.0"}
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as http_client:
            response = await http_client.get(url, headers=headers)
        if response.status_code == 200:
            return response.json().get('posts', [])
        return None
    except:
        return None

# ==============================================================================
# INPUT DRIVER
# ==============================================================================
async def read_input_line(reader, writer):
    buf = ""
    while True:
        char = await reader.read(1)
        if not char: return None
        if char in ('\r', '\n'): return buf.strip()
        elif char in ('\x08', '\x7f'):
            if len(buf) > 0:
                buf = buf[:-1]
                writer.write("\x08 \x08")
                await writer.drain()
        else:
            buf += char
            writer.write(char)
            await writer.drain()

# ==============================================================================
# MAIN AS/400 SYSTEM CONTROLLER
# ==============================================================================
async def shell(reader, writer):
    draw_as400_header(writer, "MAIN TERMINAL OPERATIONS MENU")
    
    writer.write("\x1b[5;1H\x1b[1;32mSelect one of the following:\x1b[0m\r\n\r\n")
    writer.write("     \x1b[1;37m1.\x1b[0m Go to Board (Command: GO <board>)\r\n")
    writer.write("     \x1b[1;37m2.\x1b[0m View Thread Component (Command: VIEW <option_number>)\r\n")
    writer.write("     \x1b[1;37m90.\x1b[0m Signoff Mainframe (Command: EXIT)\r\n\r\n")
    writer.write("\x1b[1;34m" + "." * TERMINAL_COLS + "\x1b[0m\r\n")
    
    draw_as400_footer(writer, has_more=False)
    await writer.drain()

    session_threads = {}
    active_board = ""
    current_view_mode = "MENU"
    previous_view_mode = "MENU" 
    active_thread_id = ""
    active_download_struct = None 
    
    active_thread_line_buffer = []
    current_page_images = [] 
    
    catalog_page = 1
    thread_page = 1
    has_more_records = False

    while True:
        writer.write("\x1b[23;22H\x1b[K")
        await writer.drain()
        
        command_line = await read_input_line(reader, writer)
        
        if command_line is None or command_line.upper() in ("EXIT", "90"):
            writer.write("\x1b[24;1H\r\nSIGNOFF COMPLETED SYSTEM CONSOLE TERMINATED.\r\n")
            await writer.drain()
            break
            
        if not command_line:
            if current_view_mode == "MEDIA_PANE":
                command_line = "REDRAW_PREVIOUS_PANEL"
            else:
                continue
        
        cmd_upper = command_line.upper()
            
        if cmd_upper == "REDRAW_PREVIOUS_PANEL":
            current_view_mode = previous_view_mode
            if current_view_mode == "CATALOG":
                command_line = f"GO {active_board}"
                threads_data, _, _ = await fetch_board_catalog(active_board, catalog_page)
                draw_as400_header(writer, "BOARD CATALOG RESOURCE LIST", current_board=active_board, page_num=catalog_page)
                await render_catalog_pure_python(threads_data, writer)
                draw_as400_footer(writer, has_more=has_more_records)
                await writer.drain()
                continue
            elif current_view_mode == "THREAD":
                command_line = "RENDER_THREAD_PAGE"

        if cmd_upper == "DL" and current_view_mode == "MEDIA_PANE" and active_download_struct:
            writer.write("\x1b[21;1H\x1b[K\x1b[1;31mCPF0870: ZMODEM pipeline offline for optimization.\x1b[0m")
            await writer.drain()
            await asyncio.sleep(1.0)
            command_line = "REDRAW_PREVIOUS_PANEL"
            cmd_upper = "REDRAW_PREVIOUS_PANEL"
                
        if cmd_upper == "IMG" or cmd_upper.startswith("IMG "):
            target_img_struct = None
            if current_view_mode in ("THREAD", "CATALOG"):
                previous_view_mode = current_view_mode 
                try:
                    parts = cmd_upper.split(" ")
                    if len(parts) == 2:
                        target_idx = int(parts[1].strip()) - 1
                        if 0 <= target_idx < len(current_page_images):
                            target_img_struct = current_page_images[target_idx]
                    else:
                        if current_page_images:
                            target_img_struct = current_page_images[0]
                except:
                    pass
                
                if target_img_struct:
                    current_view_mode = "MEDIA_PANE"
                    active_download_struct = target_img_struct 
                    draw_as400_header(writer, f"SPOOL MEDIA SPLIT PANEL VIEW", current_board=active_board)
                    writer.write(f"\x1b[5;1H\x1b[K\x1b[1;32mCommands: \x1b[1;30mDL (Offline)\x1b[1;32m | \x1b[1;37m[ENTER]\x1b[1;32m = Return to text listings\x1b[0m")
                    await writer.drain()
                    await render_split_media_pane(target_img_struct, active_board, writer, start_row=6)
                else:
                    writer.write("\x1b[21;1H\x1b[K\x1b[1;31mCPF0801: Enumerated image reference parameter match not found on page.\x1b[0m")
                await writer.drain()
                continue

        is_paging_command = command_line in ("+", "-")
        if is_paging_command:
            if current_view_mode == "MENU":
                writer.write("\x1b[21;1H\x1b[K\x1b[1;31mCPF0044: No record streams active.\x1b[0m")
                await writer.drain()
                continue
                
            if command_line == "+":
                if not has_more_records:
                    writer.write("\x1b[21;1H\x1b[K\x1b[1;31mCPF0045: Reached terminal boundary bounds.\x1b[0m")
                    await writer.drain()
                    continue
                if current_view_mode == "CATALOG": catalog_page += 1
                if current_view_mode == "THREAD": thread_page += 1
            elif command_line == "-":
                if current_view_mode == "CATALOG" and catalog_page <= 1:
                    writer.write("\x1b[21;1H\x1b[K\x1b[1;31mCPF0046: Positioned at root directory indexes.\x1b[0m")
                    await writer.drain()
                    continue
                if current_view_mode == "THREAD" and thread_page <= 1:
                    command_line = f"GO {active_board}"
                    is_paging_command = False
                else:
                    if current_view_mode == "CATALOG": catalog_page -= 1
                    if current_view_mode == "THREAD": thread_page -= 1
            
            if is_paging_command:
                command_line = f"GO {active_board}" if current_view_mode == "CATALOG" else f"RENDER_THREAD_PAGE"

        if command_line.upper().startswith("GO ") or (command_line == "1"):
            cmd_cleaned = command_line.strip()
            if not is_paging_command and cmd_cleaned.upper() != "REDRAW_PREVIOUS_PANEL":
                board_target = "g" if cmd_cleaned == "1" else cmd_cleaned[3:].strip().lower()
                active_board = board_target
                catalog_page = 1
                
            current_view_mode = "CATALOG"
            draw_as400_header(writer, "BOARD CATALOG RESOURCE LIST", current_board=active_board, page_num=catalog_page)
            
            threads_data, threads_map, has_more_records = await fetch_board_catalog(active_board, catalog_page)
            session_threads = threads_map  
            
            current_page_images = []
            for t_idx in range(1, 11):
                s_key = str(t_idx)
                if s_key in session_threads and session_threads[s_key]["img"]:
                    current_page_images.append(session_threads[s_key]["img"])
            
            if not threads_data:
                writer.write(f"\x1b[5;1H\x1b[1;31mCPF0099: Unable to pull active catalog allocations.\x1b[0m")
                draw_as400_footer(writer, has_more=False)
                await writer.drain()
                continue
                
            await render_catalog_pure_python(threads_data, writer)
            draw_as400_footer(writer, has_more=has_more_records)
            await writer.drain()
                
        elif command_line.upper().startswith("VIEW ") or command_line.isdigit() or command_line == "RENDER_THREAD_PAGE":
            if command_line != "RENDER_THREAD_PAGE":
                target_num = command_line if command_line.isdigit() else command_line[5:].strip()
                if target_num.startswith("0") and len(target_num) > 1: target_num = target_num[1:]
                    
                if target_num not in session_threads:
                    writer.write("\x1b[21;1H\x1b[K\x1b[1;31mCPF0022: Option location not initialized.\x1b[0m")
                    await writer.drain()
                    continue
                    
                target_info = session_threads[target_num]
                active_thread_id = target_info["id"]
                thread_page = 1
                
                posts_data = await fetch_full_thread(active_board, active_thread_id)
                if not posts_data:
                    writer.write(f"\x1b[5;1H\x1b[1;31mCPF0098: Thread records unreadable.\x1b[0m\r\n")
                    draw_as400_footer(writer, has_more=False)
                    await writer.drain()
                    continue
                active_thread_line_buffer = generate_thread_line_buffer(posts_data)
                
            current_view_mode = "THREAD"
            draw_as400_header(writer, f"DISPLAY THREAD WORKSTATION CONTROL - No.{active_thread_id}", current_board=active_board, page_num=thread_page)
            
            start_line_idx = (thread_page - 1) * 15
            end_line_idx = start_line_idx + 15
            lines_to_print = active_thread_line_buffer[start_line_idx:end_line_idx]
            has_more_records = len(active_thread_line_buffer) > end_line_idx
            
            current_page_images = []
            for line_obj in lines_to_print:
                if line_obj["is_header"] and line_obj["img"]:
                    current_page_images.append(line_obj["img"])
            
            current_row = 5
            img_seq_counter = 1
            for line_obj in lines_to_print:
                out_text = line_obj["text"]
                if "[IMAGE_PLACEHOLDER]" in out_text:
                    out_text = out_text.replace("[IMAGE_PLACEHOLDER]", f"\x1b[1;36m[IMG {img_seq_counter}]\x1b[0m")
                    img_seq_counter += 1
                    
                writer.write(f"\x1b[{current_row};1H\x1b[K{out_text}")
                current_row += 1
                
            draw_as400_footer(writer, has_more=has_more_records)
            await writer.drain()
        else:
            writer.write("\x1b[21;1H\x1b[K\x1b[1;31mCPF0001: Command input parameter syntax invalid.\x1b[0m")
            await writer.drain()

    writer.close()

async def main():
    try:
        server = await create_server(host='0.0.0.0', port=TELNET_PORT, shell=shell)
        print("==================================================================")
        print(f" AS/400 SYSTEM UTILITIES SUBSYSTEM LAYER V4R5: OPERATIONAL       ")
        print(f" Multi-Media Pipeline Endpoint Bound on Port: TCP:{TELNET_PORT}   ")
        print("==================================================================")
        await server.wait_closed()
    except Exception as e:
        print(f"[CRITICAL FAILURE: {str(e)}]", file=sys.stderr)

if __name__ == '__main__':
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nSubsystem power-down routine complete.")
