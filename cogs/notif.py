import discord
from discord.ext import commands, tasks
import json
import re
import os
import asyncio
import urllib.parse
import yt_dlp
import functools
import uuid
import aiohttp
import datetime
from functools import partial
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions

from dotenv import load_dotenv 
import base64
import tempfile

load_dotenv()

API_KEYS = []
if os.getenv("GOOGLE_API_KEY"):
    API_KEYS.append(os.getenv("GOOGLE_API_KEY"))

key_index = 1
while True:
    extra_key = os.getenv(f"GOOGLE_API_KEY_{key_index}")
    if extra_key:
        API_KEYS.append(extra_key)
        key_index += 1
    else:
        break

current_key_idx = 0

def configure_genai():
    global current_key_idx
    if API_KEYS:
        genai.configure(api_key=API_KEYS[current_key_idx])

def rotate_api_key():
    global current_key_idx
    if len(API_KEYS) > 1:
        current_key_idx = (current_key_idx + 1) % len(API_KEYS)
        configure_genai()
        return True
    return False

configure_genai()

def _get_youtube_video_id(url):
    if not url: return None
    url = url.replace('\\', '')
    youtube_regex = r'(?:https?:\/\/)?(?:[a-zA-Z0-9-]+\.)?(?:youtube(?:-nocookie)?\.com\/(?:[^\/\n\s]+\/\S+\/|(?:v|e(?:mbed)?)\/|.*[?&]v=|watch\?.*&v=|live\/|shorts\/)|youtu\.be\/)([a-zA-Z0-9_-]{11})'
    match = re.search(youtube_regex, url)
    return match.group(1) if match else None

def _extract_youtube_info(url, cookiefile_path=None):
    ydl_opts = {
        'quiet': True,
        'skip_download': True,
        'force_generic_extractor': True,
        'no_warnings': True,
        'extractor_args': {'youtube': {'skip': ['dash']}},
        'format': 'best'
    }
    
    if cookiefile_path:
        ydl_opts['cookiefile'] = cookiefile_path
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get('title')
            description = info.get('description', '')
            video_url = info.get('webpage_url', url)
            thumbnail_url = None
            
            thumbnails = info.get('thumbnails', [])
            priority_ids = ['maxres', 'standard', 'high']
            for id_ in priority_ids:
                for t in thumbnails:
                    if t.get('id') == id_:
                        thumbnail_url = t.get('url')
                        break
                if thumbnail_url: break
            if not thumbnail_url and thumbnails: 
                thumbnail_url = thumbnails[-1].get('url')

            return title, description, thumbnail_url, video_url
            
    except Exception:
        video_id = _get_youtube_video_id(url)
        if video_id:
            fallback_thumbnail = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
            return None, None, fallback_thumbnail, url
            
        return None, None, None, url


def get_config_path(cog, path_id, type_key, field_key=None):
    path_data = cog.config["notification_paths"].get(path_id)
    if not path_data: return None
    
    path = path_data["custom_messages"][type_key]
    return path.get(field_key, "") if field_key else path

class TextModal(discord.ui.Modal):
    def __init__(self, title, label, default_value, parent_view, type_key, field_key, path_id):
        super().__init__(title=title)
        self.parent_view = parent_view
        self.type_key = type_key
        self.field_key = field_key
        self.path_id = path_id
        self.text_input = discord.ui.TextInput(
            label=label,
            style=discord.TextStyle.paragraph if field_key == 'description' else discord.TextStyle.short,
            default=default_value,
            required=False,
            max_length=4000 if field_key == 'description' else (256 if field_key == 'title' else 2000)
        )
        self.add_item(self.text_input)

    async def on_submit(self, interaction: discord.Interaction):
        self.parent_view.cog.config["notification_paths"][self.path_id]["custom_messages"][self.type_key][self.field_key] = self.text_input.value
        self.parent_view.cog.save_config()
        await interaction.response.edit_message(embed=self.parent_view.build_embed(), view=self.parent_view)

class ButtonLabelModal(discord.ui.Modal, title="Atur Tombol Notifikasi"):
    def __init__(self, parent_view, type_key, path_id):
        super().__init__()
        self.parent_view = parent_view
        self.type_key = type_key
        self.path_id = path_id
        current_label = get_config_path(parent_view.cog, path_id, type_key, "button_label")
        self.label_input = discord.ui.TextInput(
            label="Label Tombol",
            default=current_label,
            style=discord.TextStyle.short,
            max_length=80
        )
        self.add_item(self.label_input)

    async def on_submit(self, interaction: discord.Interaction):
        self.parent_view.cog.config["notification_paths"][self.path_id]["custom_messages"][self.type_key]["button_label"] = self.label_input.value
        self.parent_view.cog.save_config()
        await interaction.response.edit_message(embed=self.parent_view.build_embed(), view=self.parent_view.build_color_view())

class ColorInputModal(discord.ui.Modal, title="Atur Warna Custom"):
    def __init__(self, parent_view, type_key, path_id, color_type):
        super().__init__()
        self.parent_view = parent_view
        self.type_key = type_key
        self.path_id = path_id
        self.color_type = color_type
        
        current_color = get_config_path(parent_view.cog, path_id, type_key, 
                                       "embed_color" if color_type == 'embed' else "button_color")
        
        self.color_input = discord.ui.TextInput(
            label=f"Warna HEX {color_type.capitalize()}",
            default=current_color or "#3498db",
            style=discord.TextStyle.short,
            max_length=7,
            placeholder="#FFFFFF"
        )
        self.add_item(self.color_input)

    async def on_submit(self, interaction: discord.Interaction):
        color_value = self.color_input.value.strip()
        
        if not re.match(r'^#[0-9A-Fa-f]{6}$', color_value):
            await interaction.response.send_message("Format warna HEX tidak valid! Gunakan format: #RRGGBB", ephemeral=True)
            return
        
        if self.color_type == 'embed':
            self.parent_view.cog.config["notification_paths"][self.path_id]["custom_messages"][self.type_key]["embed_color"] = color_value
        else:
            self.parent_view.cog.config["notification_paths"][self.path_id]["custom_messages"][self.type_key]["button_color"] = color_value
            
        self.parent_view.cog.save_config()
        await interaction.response.edit_message(embed=self.parent_view.build_embed(), view=self.parent_view.build_color_view())

class ButtonColorView(discord.ui.View):
    def __init__(self, parent_view, type_key, path_id):
        super().__init__(timeout=180)
        self.parent_view = parent_view
        self.type_key = type_key
        self.path_id = path_id
        self._create_buttons()

    def _create_buttons(self):
        preset_colors = [
            ("Biru Primary", discord.ButtonStyle.primary, "#5865f2"),
            ("Abu Secondary", discord.ButtonStyle.secondary, "#95a5a6"),
            ("Hijau Success", discord.ButtonStyle.success, "#57f287"),
            ("Merah Danger", discord.ButtonStyle.danger, "#ed4245")
        ]
        
        embed_colors = [
            ("Merah Live", "#e74c3c"),
            ("Hijau Upload", "#2ecc71"),
            ("Biru Default", "#3498db"),
            ("Ungu Premium", "#9b59b6"),
            ("Emas", "#f1c40f"),
            ("Oranye", "#e67e22"),
            ("Teal", "#1abc9c"),
            ("Navy", "#34495e")
        ]
        
        self.add_item(discord.ui.Button(label="WARNA TOMBOL", style=discord.ButtonStyle.grey, disabled=True, row=0))
        
        for label, style, hex_color in preset_colors:
            button = discord.ui.Button(label=label, style=style, row=1)
            button.callback = partial(self._on_button_color_selected, btn_style_value=style.value, btn_hex=hex_color)
            self.add_item(button)
        
        self.add_item(discord.ui.Button(label="WARNA EMBED", style=discord.ButtonStyle.grey, disabled=True, row=2))
        
        for label, hex_color in embed_colors[:4]:
            button = discord.ui.Button(label=label, style=discord.ButtonStyle.primary, row=3)
            button.callback = partial(self._on_embed_color_selected, embed_hex=hex_color)
            self.add_item(button)
        
        for label, hex_color in embed_colors[4:]:
            button = discord.ui.Button(label=label, style=discord.ButtonStyle.primary, row=4)
            button.callback = partial(self._on_embed_color_selected, embed_hex=hex_color)
            self.add_item(button)
        
        custom_embed_btn = discord.ui.Button(label="Custom Warna Embed", style=discord.ButtonStyle.secondary, row=0)
        async def custom_embed_callback(interaction: discord.Interaction):
            await interaction.response.send_modal(ColorInputModal(self.parent_view, self.type_key, self.path_id, 'embed'))
        custom_embed_btn.callback = custom_embed_callback
        self.add_item(custom_embed_btn)

        custom_button_btn = discord.ui.Button(label="Custom Warna Tombol", style=discord.ButtonStyle.secondary, row=0)
        async def custom_button_callback(interaction: discord.Interaction):
            await interaction.response.send_modal(ColorInputModal(self.parent_view, self.type_key, self.path_id, 'button'))
        custom_button_btn.callback = custom_button_callback
        self.add_item(custom_button_btn)
            
        cancel_button = discord.ui.Button(label="Batalkan", style=discord.ButtonStyle.red, row=4)
        async def cancel_callback(interaction: discord.Interaction):
            await interaction.response.edit_message(embed=self.parent_view.build_embed(), view=self.parent_view)
            self.stop()
        cancel_button.callback = cancel_callback
        self.add_item(cancel_button)

    async def _on_button_color_selected(self, interaction: discord.Interaction, btn_style_value, btn_hex):
        config_msg = self.parent_view.cog.config["notification_paths"][self.path_id]["custom_messages"][self.type_key]
        config_msg["button_style"] = btn_style_value
        config_msg["button_color"] = btn_hex
        self.parent_view.cog.save_config()
        await interaction.response.edit_message(embed=self.parent_view.build_embed(), view=self.parent_view)
        self.stop()

    async def _on_embed_color_selected(self, interaction: discord.Interaction, embed_hex):
        config_msg = self.parent_view.cog.config["notification_paths"][self.path_id]["custom_messages"][self.type_key]
        config_msg["embed_color"] = embed_hex
        self.parent_view.cog.save_config()
        await interaction.response.edit_message(embed=self.parent_view.build_embed(), view=self.parent_view)
        self.stop()

class MessageConfigView(discord.ui.View):
    def __init__(self, cog, type_key, path_id):
        super().__init__(timeout=180)
        self.cog = cog
        self.type_key = type_key
        self.path_id = path_id

    def build_embed(self):
        path_data = self.cog.config["notification_paths"][self.path_id]
        config_msg = path_data["custom_messages"][self.type_key]
        
        embed_color_hex = config_msg.get('embed_color', '#3498db') 
        button_color_hex = config_msg.get('button_color', '#5865f2')
        
        try:
            color_int = int(embed_color_hex.strip("#"), 16)
            embed_color = discord.Color(color_int)
        except:
            embed_color = discord.Color.blue()
            embed_color_hex = "#3498db"

        source_id = path_data["source_id"]
        target_id = path_data["target_id"]
        
        source_channel = self.cog.bot.get_channel(source_id)
        target_channel = self.cog.bot.get_channel(target_id)
        
        source_info = f"#{source_channel.name} ({source_channel.guild.name})" if source_channel and source_channel.guild else f"ID: {source_id}"
        target_info = f"#{target_channel.name} ({target_channel.guild.name})" if target_channel and target_channel.guild else f"ID: {target_id}"

        embed = discord.Embed(
            title=f"Pengaturan Pesan: {self.type_key.upper()}",
            description=f"**Jalur:** {source_info} $\\rightarrow$ {target_info}\n**ID Jalur:** `{self.path_id}`",
            color=embed_color
        )
        
        embed.add_field(name="Isi Pesan Biasa", value=f"`{config_msg.get('content') or 'Belum diatur'}`\n*(Gunakan: {{ai_hype}} buat teks Jarkasih kalcer)*", inline=False)
        embed.add_field(name="Judul Embed", value=f"`{config_msg.get('title') or 'Belum diatur'}` (Gunakan: {{judul}})", inline=False)
        embed.add_field(name="Deskripsi Embed", value=f"`{config_msg.get('description') or 'Belum diatur'}` (Gunakan: {{deskripsi}}, {{url}})", inline=False)
        embed.add_field(name="Label Tombol", value=f"`{config_msg.get('button_label') or 'Belum diatur'}`", inline=False)
        
        button_style_value = config_msg.get('button_style', discord.ButtonStyle.primary.value)
        try:
            button_style_name = discord.ButtonStyle(button_style_value).name.capitalize().replace('_', ' ')
        except ValueError:
            button_style_name = "Primary"
        
        use_embed = config_msg.get('use_embed', True)
        embed_thumb = config_msg.get('embed_thumbnail', True)

        embed.add_field(name="Style Tombol", value=f"`{button_style_name}`", inline=True)
        embed.add_field(name="Warna Tombol", value=f"`{button_color_hex}`", inline=True)
        embed.add_field(name="Warna Samping Embed", value=f"`{embed_color_hex}`", inline=True)
        embed.add_field(name="Status Embed", value=f"**`{'Aktif' if use_embed else 'Mati'}`**", inline=True)
        embed.add_field(name="Status Thumbnail", value=f"**`{'Aktif' if embed_thumb else 'Mati'}`**", inline=True)
        
        color_preview = f"**Preview Warna:**\n"
        color_preview += f"Embed: ████ `{embed_color_hex}`\n"
        color_preview += f"Tombol: ████ `{button_color_hex}`"
        embed.add_field(name="\u200b", value=color_preview, inline=False)
        
        return embed

    def build_color_view(self):
        return ButtonColorView(self, self.type_key, self.path_id)

    @discord.ui.button(label="Atur Pesan Biasa", style=discord.ButtonStyle.secondary, row=0)
    async def set_content_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        current_value = get_config_path(self.cog, self.path_id, self.type_key, "content")
        await interaction.response.send_modal(TextModal("Atur Pesan Teks Biasa", "Isi Pesan", current_value, self, self.type_key, "content", self.path_id))

    @discord.ui.button(label="Atur Judul Embed", style=discord.ButtonStyle.secondary, row=0)
    async def set_title_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        current_value = get_config_path(self.cog, self.path_id, self.type_key, "title")
        await interaction.response.send_modal(TextModal("Atur Judul Embed", "Judul Embed", current_value, self, self.type_key, "title", self.path_id))

    @discord.ui.button(label="Atur Deskripsi Embed", style=discord.ButtonStyle.secondary, row=0)
    async def set_desc_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        current_value = get_config_path(self.cog, self.path_id, self.type_key, "description")
        await interaction.response.send_modal(TextModal("Atur Deskripsi Embed", "Deskripsi Embed", current_value, self, self.type_key, "description", self.path_id))
        
    @discord.ui.button(label="Atur Tombol & Warna", style=discord.ButtonStyle.secondary, row=1)
    async def set_button_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ButtonLabelModal(self, self.type_key, self.path_id))
        
    @discord.ui.button(label="Atur Warna Custom", style=discord.ButtonStyle.primary, row=1)
    async def set_custom_color_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(view=self.build_color_view())
        
    @discord.ui.button(label="Toggle Status Embed", style=discord.ButtonStyle.secondary, row=2)
    async def toggle_embed_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        config_msg = self.cog.config["notification_paths"][self.path_id]["custom_messages"][self.type_key]
        current_state = config_msg.get('use_embed', True)
        config_msg['use_embed'] = not current_state
        self.cog.save_config()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)
        
    @discord.ui.button(label="Toggle Status Thumbnail", style=discord.ButtonStyle.secondary, row=2)
    async def toggle_thumbnail_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        config_msg = self.cog.config["notification_paths"][self.path_id]["custom_messages"][self.type_key]
        current_state = config_msg.get('embed_thumbnail', True)
        config_msg['embed_thumbnail'] = not current_state
        self.cog.save_config()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)
        
    @discord.ui.button(label="← Pilih Tipe Lain", style=discord.ButtonStyle.secondary, row=3)
    async def back_to_type_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        type_select_view = TypeSelectView(self.cog, interaction.guild.id, self.path_id)
        await interaction.response.edit_message(content=f"Jalur dipilih: `{self.path_id}`. Pilih Tipe Pesan:", embed=None, view=type_select_view)
        self.stop()

    @discord.ui.button(label="Selesai", style=discord.ButtonStyle.green, row=3)
    async def finish_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        type_select_view = TypeSelectView(self.cog, interaction.guild.id, self.path_id)
        await interaction.response.edit_message(content=f"Pengaturan `{self.type_key}` tersimpan. Jalur: `{self.path_id}`. Pilih Tipe Pesan lain atau tutup pesan ini:", embed=None, view=type_select_view)
        self.stop()

class PathSelectView(discord.ui.View):
    def __init__(self, cog, guild_id):
        super().__init__(timeout=180)
        self.cog = cog
        self.guild_id = guild_id
        self._add_path_select()

    def _get_path_options(self):
        options = []
        for path_id, data in self.cog.config["notification_paths"].items():
            source_id = data['source_id']
            source_channel = self.cog.bot.get_channel(source_id)
            if source_channel and source_channel.guild.id != self.guild_id:
                continue
                
            target_id = data['target_id']
            target_channel = self.cog.bot.get_channel(target_id)

            source_name = f"#{source_channel.name}" if source_channel else f"ID {source_id}"
            target_name = f"#{target_channel.name}" if target_channel else f"ID {target_id}"

            label = f"{source_name} → {target_name}"
            options.append(discord.SelectOption(label=label[:100], value=path_id))

        return options

    def _add_path_select(self):
        options = self._get_path_options()
        
        if not options:
            self.add_item(discord.ui.Button(label="Tidak ada Jalur Notifikasi terdaftar di Server ini", style=discord.ButtonStyle.red, disabled=True))
            return

        path_select = discord.ui.Select(
            placeholder="Pilih Jalur Notifikasi yang akan dikonfigurasi...",
            options=options,
            custom_id="path_select_menu"
        )

        async def callback(interaction: discord.Interaction):
            selected_path_id = path_select.values[0]
            type_select_view = TypeSelectView(self.cog, self.guild_id, selected_path_id)
            await interaction.response.edit_message(content=f"Jalur dipilih: `{selected_path_id}`. Pilih Tipe Pesan:", view=type_select_view)
            self.stop()
            
        path_select.callback = callback
        self.add_item(path_select)

class TypeSelectView(discord.ui.View):
    def __init__(self, cog, guild_id, path_id):
        super().__init__(timeout=180)
        self.cog = cog
        self.guild_id = guild_id
        self.path_id = path_id
        
        options = []
        for key in self.cog.default_messages.keys():
            options.append(discord.SelectOption(label=key.capitalize().replace('_', ' '), value=key))
            
        type_select = discord.ui.Select(
            placeholder="Pilih Tipe Pesan...",
            options=options,
            custom_id="type_select_menu"
        )
        
        async def callback(interaction: discord.Interaction):
            selected_type_key = type_select.values[0]
            message_config_view = MessageConfigView(self.cog, selected_type_key, self.path_id)
            await interaction.response.edit_message(content=None, embed=message_config_view.build_embed(), view=message_config_view)
            self.stop()
        
        type_select.callback = callback
        self.add_item(type_select)
        
        back_button = discord.ui.Button(label="← Ganti Jalur", style=discord.ButtonStyle.secondary, row=1)
        async def back_callback(interaction: discord.Interaction):
             await interaction.response.edit_message(content="Pilih Jalur Notifikasi yang akan dikonfigurasi:", view=PathSelectView(self.cog, self.guild_id))
             self.stop()
        back_button.callback = back_callback
        self.add_item(back_button)

class Notif(commands.Cog, name="🔔 Notification"):
    def __init__(self, bot):
        self.bot = bot
        self.config_file = "data/notif.json"
        
        self.default_messages = self._get_default_messages() 
        self.config = self._load_config()
        self.daily_reset_task.start()

    def cog_unload(self):
        self.daily_reset_task.cancel()

    async def _extract_url_from_message(self, message):
        content_clean = message.content.replace('\\', '')
        
        markdown_url_pattern = r'\[.*?\]\((https?://[^\)]+)\)'
        markdown_match = re.search(markdown_url_pattern, content_clean)
        if markdown_match:
            return markdown_match.group(1)
        
        general_url_pattern = re.compile(r'https?://[^\s<>"]+|www\.[^\s<>"]+')
        match = general_url_pattern.search(content_clean)
        if match:
            return match.group(0).rstrip(').,!')
            
        youtu_pattern = re.compile(r'youtu\.be/[a-zA-Z0-9_-]{11}')
        match2 = youtu_pattern.search(content_clean)
        if match2:
            return "https://" + match2.group(0)
        
        return None

    async def _detect_youtube_link(self, url, message_content):
        url = url.replace('\\', '')
        content_clean = message_content.replace('\\', '').lower()
        youtube_regex = r'(?:https?:\/\/)?(?:[a-zA-Z0-9-]+\.)?(?:youtube(?:-nocookie)?\.com\/(?:[^\/\n\s]+\/\S+\/|(?:v|e(?:mbed)?)\/|.*[?&]v=|watch\?.*&v=|live\/|shorts\/)|youtu\.be\/)([a-zA-Z0-9_-]{11})'
        
        if re.search(youtube_regex, url):
            if "live" in content_clean or "/live/" in url or "youtube.com/live/" in url:
                return "live", url
            elif "premier" in content_clean or "premiere" in content_clean:
                return "premier", url
            else:
                return "upload", url
        
        return None, url

    async def _detect_tiktok_link(self, url):
        url = url.replace('\\', '')
        
        live_match = re.search(r'tiktok\.com/@([\w.-]+)/live', url, re.IGNORECASE)
        if live_match:
            return "tiktok_live", url

        tiktok_patterns = [
            r'(?:https?:\/\/)?(?:[\w-]+\.)?tiktok\.com/(?:@[\w.-]+\/)?video/(\d+)',
            r'(?:https?:\/\/)?(?:[\w-]+\.)?tiktok\.com/(?:@[\w.-]+\/)?t/(\w+)',
            r'(?:https?:\/\/)?(?:[\w-]+\.)?tiktok\.com/t/(\w+)',
            r'(?:https?:\/\/)?(?:vm|vt|m)\.tiktok\.com/(\w+)'
        ]

        for pattern in tiktok_patterns:
            if re.search(pattern, url, re.IGNORECASE):
                if "vm.tiktok.com" in url or "vt.tiktok.com" in url:
                    try:
                        timeout = aiohttp.ClientTimeout(total=10)
                        async with aiohttp.ClientSession(timeout=timeout) as session:
                            async with session.get(url, allow_redirects=True) as response:
                                final_url = str(response.url)
                                if "tiktok.com" in final_url:
                                    url = final_url
                    except Exception:
                        pass

                    resolved_live_match = re.search(r'tiktok\.com/@([\w.-]+)/live', url, re.IGNORECASE)
                    if resolved_live_match:
                        return "tiktok_live", url
                
                if "www.tiktok.com" not in url and "tiktok.com" in url:
                    url = url.replace("tiktok.com", "www.tiktok.com")
                
                return "tiktok", url
        
        return None, url

    async def _detect_instagram_link(self, url):
        url = url.replace('\\', '')
        
        live_match = re.search(r'instagram\.com/([A-Za-z0-9_.]+)/live', url, re.IGNORECASE)
        if live_match:
            return "instagram_live", url
        
        ig_patterns = [
            r'instagram\.com/p/([A-Za-z0-9_-]+)',
            r'instagram\.com/reel/([A-Za-z0-9_-]+)',
            r'instagram\.com/tv/([A-Za-z0-9_-]+)'
        ]
        
        for pattern in ig_patterns:
            if re.search(pattern, url, re.IGNORECASE):
                return "instagram", url
                
        return None, url

    async def _get_link_from_url(self, message):
        url = await self._extract_url_from_message(message)
        if not url:
            return None, None
        
        link_type, final_url = await self._detect_youtube_link(url, message.content)
        if link_type:
            return link_type, final_url
        
        link_type, final_url = await self._detect_tiktok_link(url)
        if link_type:
            return link_type, final_url
            
        link_type, final_url = await self._detect_instagram_link(url)
        if link_type:
            return link_type, final_url
        
        return None, None
    
    def _get_unique_video_id(self, url):
        if not url: return None
        url = url.replace('\\', '')
        
        youtube_regex = r'(?:https?:\/\/)?(?:[a-zA-Z0-9-]+\.)?(?:youtube(?:-nocookie)?\.com\/(?:[^\/\n\s]+\/\S+\/|(?:v|e(?:mbed)?)\/|.*[?&]v=|watch\?.*&v=|live\/|shorts\/)|youtu\.be\/)([a-zA-Z0-9_-]{11})'
        match = re.search(youtube_regex, url)
        if match:
            return f"yt_{match.group(1)}"

        tk_live_match = re.search(r'tiktok\.com/@([\w.-]+)/live', url, re.IGNORECASE)
        if tk_live_match:
            return f"tk_live_{tk_live_match.group(1)}"

        tiktok_patterns = [
            r'(?:https?:\/\/)?(?:[\w-]+\.)?tiktok\.com/(?:@[\w.-]+\/)?video/(\d+)',
            r'(?:https?:\/\/)?(?:[\w-]+\.)?tiktok\.com/(?:@[\w.-]+\/)?t/(\w+)',
            r'(?:https?:\/\/)?(?:[\w-]+\.)?tiktok\.com/t/(\w+)',
            r'(?:https?:\/\/)?(?:vm|vt|m)\.tiktok\.com/(\w+)'
        ]
        
        for pattern in tiktok_patterns:
            match = re.search(pattern, url, re.IGNORECASE)
            if match:
                return f"tk_{match.group(1)}"

        ig_live_match = re.search(r'instagram\.com/([A-Za-z0-9_.]+)/live', url, re.IGNORECASE)
        if ig_live_match:
            return f"ig_live_{ig_live_match.group(1)}"

        ig_match = re.search(r'instagram\.com/(?:p|reel|tv)/([A-Za-z0-9_-]+)', url, re.IGNORECASE)
        if ig_match:
            return f"ig_{ig_match.group(1)}"

        return None

    def _get_default_messages(self):
        return {
            "live": {
                "title": "[🔴 {judul}]({url})",
                "description": "Yuk gabung di live stream ini!\n\n{url}",
                "content": "@everyone {ai_hype}",
                "button_label": "Tonton Live",
                "button_style": discord.ButtonStyle.danger.value,
                "button_color": "#ed4245",
                "embed_color": "#e74c3c",
                "use_embed": False,
                "embed_thumbnail": True
            },
            "upload": {
                "title": "[✨ {judul}]({url})",
                "description": "Video baru diupload, jangan sampai ketinggalan!\n\n{url}",
                "content": "@everyone {ai_hype}",
                "button_label": "Tonton Video",
                "button_style": discord.ButtonStyle.primary.value,
                "button_color": "#5865f2",
                "embed_color": "#2ecc71",
                "use_embed": False,
                "embed_thumbnail": True
            },
            "premier": {
                "title": "[🎬 Premiere Segera: {judul}]({url})",
                "description": "Video premiere akan segera tayang!\n\n{url}",
                "content": "@everyone {ai_hype}",
                "button_label": "Tonton Premiere",
                "button_style": discord.ButtonStyle.success.value,
                "button_color": "#57f287",
                "embed_color": "#9b59b6",
                "use_embed": False,
                "embed_thumbnail": True
            },
            "tiktok": {
                "title": "[📱 {judul}]({url})",
                "description": "Cek video TikTok terbaru!\n\n{url}",
                "content": "@everyone {ai_hype}",
                "button_label": "Tonton di TikTok",
                "button_style": discord.ButtonStyle.primary.value,
                "button_color": "#000000",
                "embed_color": "#000000",
                "use_embed": False,
                "embed_thumbnail": True
            },
            "tiktok_live": {
                "title": "[🔴 TikTok Live]({url})",
                "description": "Ada yang lagi live di TikTok nih!\n\n{url}",
                "content": "@everyone {ai_hype}",
                "button_label": "Tonton Live TikTok",
                "button_style": discord.ButtonStyle.danger.value,
                "button_color": "#ed4245",
                "embed_color": "#e74c3c",
                "use_embed": False,
                "embed_thumbnail": True
            },
            "instagram": {
                "title": "[📸 Instagram Post]({url})",
                "description": "Ada postingan atau Reels baru di Instagram!\n\n{url}",
                "content": "@everyone {ai_hype}",
                "button_label": "Buka Instagram",
                "button_style": discord.ButtonStyle.primary.value,
                "button_color": "#E1306C",
                "embed_color": "#E1306C",
                "use_embed": False,
                "embed_thumbnail": True
            },
            "instagram_live": {
                "title": "[🔴 Instagram Live]({url})",
                "description": "Yuk join Instagram Live sekarang!\n\n{url}",
                "content": "@everyone {ai_hype}",
                "button_label": "Tonton IG Live",
                "button_style": discord.ButtonStyle.danger.value,
                "button_color": "#ed4245",
                "embed_color": "#e74c3c",
                "use_embed": False,
                "embed_thumbnail": True
            }
        }

    def _load_config(self):
        default_config = {
            "notification_paths": {}, 
            "recent_video_ids": [],
            "next_daily_reset_timestamp": None
        }
        config = {}
        try:
            with open(self.config_file, "r") as f:
                config = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        
        final_config = {**default_config, **config}
        
        keys_to_remove = ["mirrored_users", "last_daily_reset_timestamp", "last_link_after_reset"]
        for key in keys_to_remove:
            if key in final_config:
                del final_config[key]
        
        for path_id, path_data in final_config["notification_paths"].items():
            if "custom_messages" in path_data:
                for message_type in self.default_messages.keys():
                    if message_type not in path_data["custom_messages"]:
                        path_data["custom_messages"][message_type] = self.default_messages[message_type].copy()
        
        os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
        with open(self.config_file, "w") as f:
            json.dump(final_config, f, indent=4)
        return final_config

    def save_config(self):
        os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
        with open(self.config_file, "w") as f:
            json.dump(self.config, f, indent=4)
            
    async def _perform_daily_reset(self):
        now = datetime.datetime.now(datetime.UTC) 
        self.config["recent_video_ids"] = []
        
        next_reset_time = now + datetime.timedelta(hours=24)
        self.config["next_daily_reset_timestamp"] = next_reset_time.isoformat()
        
        self.save_config()

    @tasks.loop(hours=24)
    async def daily_reset_task(self):
        await self._perform_daily_reset()

    @daily_reset_task.before_loop
    async def before_daily_reset_task(self):
        await self.bot.wait_until_ready()
        
        next_reset_ts = self.config.get("next_daily_reset_timestamp")
        
        if next_reset_ts:
            try:
                next_reset_time = datetime.datetime.fromisoformat(next_reset_ts)
                now = datetime.datetime.now(datetime.UTC)
                
                delay = (next_reset_time - now).total_seconds()
                
                if delay > 0:
                    await asyncio.sleep(delay)
                else:
                    await self._perform_daily_reset()

            except Exception:
                await self._perform_daily_reset()
        else:
            await self._perform_daily_reset()

    @commands.command(name="resetcache")
    @commands.has_permissions(administrator=True)
    async def reset_cache(self, ctx):
        self.config["recent_video_ids"] = []
        self.save_config()
        await ctx.send("Cache ID video yang baru saja dikirim berhasil dibersihkan.")

    @commands.command(name="addpath")
    @commands.has_permissions(administrator=True)
    async def add_notification_path(self, ctx, source_channel_id: int, target_channel_id: int):
        if not ctx.guild:
            await ctx.send("Perintah ini hanya dapat digunakan di dalam server.")
            return
        
        for path_id, data in self.config["notification_paths"].items():
            if data["source_id"] == source_channel_id and data["target_id"] == target_channel_id:
                return await ctx.send(f"Jalur notifikasi tersebut sudah ada dengan ID Jalur `{path_id}`.")
        
        new_path_id = str(uuid.uuid4())
        self.config["notification_paths"][new_path_id] = {
            "source_id": source_channel_id,
            "target_id": target_channel_id,
            "custom_messages": self._get_default_messages()
        }
        self.save_config()
        
        source_channel = self.bot.get_channel(source_channel_id)
        target_channel = self.bot.get_channel(target_channel_id)
        source_info = f"#{source_channel.name}" if source_channel else f"ID: {source_channel_id}"
        target_info = f"#{target_channel.name}" if target_channel else f"ID: {target_channel_id}"
        
        msg = f"Jalur notifikasi baru berhasil dibuat!\n"
        msg += f"Sumber: **{source_info}**\n"
        msg += f"Tujuan: **{target_info}**\n"
        msg += f"ID Jalur: `{new_path_id}`"
        await ctx.send(msg)

    @commands.command(name="removepath")
    @commands.has_permissions(administrator=True)
    async def remove_notification_path(self, ctx, path_id: str):
        if path_id in self.config["notification_paths"]:
            del self.config["notification_paths"][path_id]
            self.save_config()
            await ctx.send(f"Jalur notifikasi dengan ID `{path_id}` berhasil dihapus.")
        else:
            await ctx.send(f"Jalur notifikasi dengan ID `{path_id}` tidak ditemukan.")

    @commands.command(name="config")
    @commands.has_permissions(administrator=True)
    async def start_config(self, ctx):
        if not ctx.guild:
            return await ctx.send("Perintah ini hanya dapat digunakan di dalam server.")
        
        view = PathSelectView(self, ctx.guild.id)
        await ctx.send("Pilih Jalur Notifikasi yang akan dikonfigurasi:", view=view)

    @commands.command(name="checkcache")
    @commands.has_permissions(administrator=True)
    async def check_cache(self, ctx):
        recent_ids = self.config.get("recent_video_ids", [])
        
        if not recent_ids:
            await ctx.send("Cache saat ini kosong.")
            return
        
        embed = discord.Embed(
            title="📦 Isi Cache Video",
            description=f"Total {len(recent_ids)} video dalam cache:",
            color=0x00ff00
        )
        
        cache_list = []
        for i, video_id in enumerate(recent_ids[-20:], 1):
            cache_list.append(f"{i}. `{video_id}`")
        
        embed.add_field(
            name="Video Terbaru (max 20)",
            value="\n".join(cache_list) if cache_list else "Tidak ada video",
            inline=False
        )
        
        embed.set_footer(text=f"Total video dalam cache: {len(recent_ids)}")
        
        await ctx.send(embed=embed)

    async def _generate_jarkasih_hype(self, link_type):
        tipe_konten_map = {
            "live": "Live Stream YouTube",
            "upload": "Video YouTube",
            "premier": "Premiere YouTube",
            "tiktok": "Video TikTok",
            "tiktok_live": "Live Stream TikTok",
            "instagram": "Postingan/Reel Instagram",
            "instagram_live": "Live Stream Instagram"
        }
        tipe_konten = tipe_konten_map.get(link_type, "Konten Terbaru")
        
        prompt = f"""
        Lu adalah Jarkasih, bot skena/kalcer ala anak Jaksel yang asik, edgy, dan ceplas-ceplos.
        Tugas lu: Kasih tau warga server kalau ada {tipe_konten} baru yang masuk.

        ATURAN GAYA BAHASA MUTLAK:
        1. WAJIB pakai gaya bahasa 'Kalcer' yang natural nyampur sama slang Western/Inggris.
        2. SANGAT PENTING: Jangan melulu pakai kata FOMO, vibes, atau legit! Lu boleh pakai sesekali, tapi rotasi dengan kosakata western lain.
        3. Campur dengan bahasa tongkrongan.
        4. Ganti-ganti mood lu.
        5. Cukup 1-2 kalimat pendek. JANGAN pakai hashtag dan JANGAN ngetik URL-nya.

        Berikan 1 respon acak lu sekarang:
        """
        
        fallback_text = f"Halo semua! Ada {tipe_konten} baru yang sudah tersedia. Yuk langsung cek dan tonton sekarang!"
        
        models_to_try = ['gemini-2.5-flash', 'gemini-3-flash-preview', 'gemini-2.5-flash-lite']
        
        for model_name in models_to_try:
            attempts = max(1, len(API_KEYS))
            for _ in range(attempts):
                try:
                    model = genai.GenerativeModel(model_name)
                    response = await asyncio.wait_for(model.generate_content_async(prompt), timeout=60.0)
                    if response.text:
                        return response.text.strip().replace('"', '')
                except asyncio.TimeoutError:
                    return fallback_text
                except google_exceptions.ResourceExhausted:
                    if rotate_api_key():
                        await asyncio.sleep(1)
                        continue
                    else:
                        break 
                except Exception:
                    break 
                    
        return fallback_text

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.id == self.bot.user.id or not message.guild:
            return
        
        paths_to_send = [data for data in self.config["notification_paths"].values() if data["source_id"] == message.channel.id]
        if not paths_to_send:
            return

        link_type, link_for_send = await self._get_link_from_url(message)
        if not link_type:
            return

        unique_id = self._get_unique_video_id(link_for_send)
        
        if unique_id:
            recent_ids = self.config.get("recent_video_ids", [])
            if unique_id in recent_ids:
                try:
                    await message.reply("⚠️ Tautan ini sudah pernah dikirim sebelumnya dan ada dalam cache. Tidak akan dikirim ulang untuk menghindari duplikasi.")
                except Exception:
                    pass
                return
                
            if "recent_video_ids" not in self.config:
                self.config["recent_video_ids"] = []
                
            self.config["recent_video_ids"].append(unique_id)
            if len(self.config["recent_video_ids"]) > 999:
                self.config["recent_video_ids"].pop(0)
            self.save_config()

        ai_hype_text = await self._generate_jarkasih_hype(link_type)

        needs_yt_dlp = link_type in ["live", "upload", "premier"]

        youtube_title, youtube_description, youtube_thumbnail, video_url = None, None, None, link_for_send
        
        if needs_yt_dlp: 
            loop = self.bot.loop
            cookie_path = None
            temp_file_name = None 
            cookies_base64 = os.getenv("COOKIES_BASE64")
            
            if cookies_base64:
                try:
                    cookies_content = base64.b64decode(cookies_base64).decode('utf-8')
                    with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8') as tf:
                        tf.write(cookies_content)
                        temp_file_name = tf.name
                    cookie_path = temp_file_name
                except Exception:
                    pass
            
            try:
                youtube_title, youtube_description, youtube_thumbnail, extracted_url = await loop.run_in_executor(
                    None, 
                    functools.partial(
                        _extract_youtube_info, 
                        link_for_send, 
                        cookiefile_path=cookie_path
                    )
                )
                if extracted_url and extracted_url != link_for_send:
                    video_url = extracted_url
            finally:
                if temp_file_name and os.path.exists(temp_file_name):
                    os.unlink(temp_file_name)

        for path_data in paths_to_send:
            target_channel_id = path_data["target_id"]
            config_msg = path_data["custom_messages"].get(link_type, self.default_messages.get(link_type))
            if not config_msg: continue

            try:
                target_channel = self.bot.get_channel(target_channel_id)
                if not target_channel: continue 

                final_content = config_msg.get('content')
                final_embed_title = config_msg.get('title')
                final_embed_description = config_msg.get('description')
                use_embed = config_msg.get('use_embed', False)

                if final_content and "{ai_hype}" in final_content:
                    final_content = final_content.replace("{ai_hype}", ai_hype_text)

                if link_type in ["live", "upload", "premier"]:
                    clean_title = youtube_title if youtube_title else "Video YouTube"
                    if youtube_title:
                        date_patterns = [
                            r'\d{4}-\d{2}-\d{2}',
                            r'\d{2}:\d{2}',
                            r'\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}'
                        ]
                        for pattern in date_patterns:
                            clean_title = re.sub(pattern, '', clean_title).strip()
                    
                    if final_content:
                        final_content = final_content.replace("{judul}", clean_title)
                        final_content = final_content.replace("{url}", video_url if self._is_valid_url(video_url) else "")
                    
                    if final_embed_title:
                        final_embed_title = final_embed_title.replace("{judul}", clean_title)
                        final_embed_title = final_embed_title.replace("{url}", video_url if self._is_valid_url(video_url) else "")
                    elif use_embed:
                        if self._is_valid_url(video_url):
                            final_embed_title = f"[{clean_title}]({video_url})"
                        else:
                            final_embed_title = clean_title

                    if final_embed_description:
                        if youtube_description:
                            desc_sub = youtube_description[:1900] + ('...' if len(youtube_description) > 1900 else '')
                            final_embed_description = final_embed_description.replace("{deskripsi}", desc_sub)
                        else:
                            final_embed_description = final_embed_description.replace("{deskripsi}", "")
                            
                        final_embed_description = final_embed_description.replace("{url}", video_url if self._is_valid_url(video_url) else "")
                    elif use_embed:
                        if youtube_description:
                            final_embed_description = youtube_description[:1900] + ('...' if len(youtube_description) > 1900 else '')
                        else:
                            final_embed_description = ""

                
                elif link_type in ["tiktok", "tiktok_live", "instagram", "instagram_live"]:
                    tipe_str = "Video TikTok"
                    if link_type == "tiktok_live": tipe_str = "TikTok Live"
                    elif link_type == "instagram": tipe_str = "Postingan Instagram"
                    elif link_type == "instagram_live": tipe_str = "Instagram Live"

                    if final_content:
                        final_content = final_content.replace("{judul}", tipe_str)
                        if self._is_valid_url(link_for_send):
                            final_content = final_content.replace("{url}", link_for_send)
                    
                    if final_embed_title:
                        final_embed_title = final_embed_title.replace("{judul}", tipe_str)
                        if self._is_valid_url(link_for_send):
                            final_embed_title = final_embed_title.replace("{url}", link_for_send)
                    elif not final_embed_title and use_embed:
                        icon_str = "📱" if "tiktok" in link_type else "📸" if link_type == "instagram" else "🔴"
                        if self._is_valid_url(link_for_send):
                            final_embed_title = f"[{icon_str} {tipe_str}]({link_for_send})"
                        else:
                            final_embed_title = f"{icon_str} {tipe_str}"

                    if final_embed_description:
                        final_embed_description = final_embed_description.replace("{deskripsi}", "")
                        if self._is_valid_url(link_for_send):
                            final_embed_description = final_embed_description.replace("{url}", link_for_send)
                    elif not final_embed_description and use_embed:
                        final_embed_description = link_for_send

                message_content = final_content
                if not use_embed:
                    if final_content:
                        message_content = f"{final_content}\n{link_for_send}"
                    else:
                        message_content = f"{ai_hype_text}\n{link_for_send}"

                embed = None
                if use_embed:
                    embed_color_hex = config_msg.get('embed_color', '#3498db')
                    try: 
                        embed_color = discord.Color(int(embed_color_hex.strip("#"), 16))
                    except: 
                        embed_color = discord.Color.blue()
                    
                    if final_embed_title or final_embed_description:
                         embed = discord.Embed(title=final_embed_title, description=final_embed_description, color=embed_color)
                         
                         if link_type in ["live", "upload", "premier"] and config_msg.get('embed_thumbnail', True) and youtube_thumbnail:
                              embed.set_image(url=youtube_thumbnail)
                         
                         if message_content is None: 
                             message_content = None
                    else:
                         message_content = final_content if final_content else link_for_send
                         if not final_content:
                              message_content = link_for_send
                         embed = None
                
                button_label = config_msg.get('button_label', 'Tonton Konten')
                button_style_value = config_msg.get('button_style', discord.ButtonStyle.primary.value)
                try: 
                    button_style = discord.ButtonStyle(button_style_value)
                except ValueError: 
                    button_style = discord.ButtonStyle.primary
                
                view = discord.ui.View()
                button = discord.ui.Button(label=button_label, style=button_style, url=link_for_send)
                view.add_item(button)

                await target_channel.send(content=message_content, embed=embed, view=view)
                
            except Exception:
                pass

    def _is_valid_url(self, url):
        try:
            result = urllib.parse.urlparse(url)
            return all([result.scheme in ['http', 'https'], result.netloc])
        except Exception:
            return False

async def setup(bot):
    os.makedirs('data', exist_ok=True)
    await bot.add_cog(Notif(bot))
