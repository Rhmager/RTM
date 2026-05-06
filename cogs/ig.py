import discord
from discord.ext import commands, tasks
import json
import os
import asyncio
import aiohttp
import logging
import re
from pymongo import MongoClient
from functools import partial

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

def get_config_path(cog, username, type_key, field_key=None):
    target_data = cog.config["targets"].get(username)
    if not target_data: return None
    path = target_data["custom_messages"][type_key]
    return path.get(field_key, "") if field_key else path

class IgTextModal(discord.ui.Modal):
    def __init__(self, title, label, default_value, parent_view, type_key, field_key, username):
        super().__init__(title=title)
        self.parent_view = parent_view
        self.type_key = type_key
        self.field_key = field_key
        self.username = username
        self.text_input = discord.ui.TextInput(
            label=label,
            style=discord.TextStyle.paragraph if field_key == 'description' else discord.TextStyle.short,
            default=default_value,
            required=False,
            max_length=4000 if field_key == 'description' else (256 if field_key == 'title' else 2000)
        )
        self.add_item(self.text_input)

    async def on_submit(self, interaction: discord.Interaction):
        self.parent_view.cog.config["targets"][self.username]["custom_messages"][self.type_key][self.field_key] = self.text_input.value
        self.parent_view.cog.save_config()
        await interaction.response.edit_message(embed=self.parent_view.build_embed(), view=self.parent_view)

class IgButtonLabelModal(discord.ui.Modal, title="Atur Tombol Notifikasi"):
    def __init__(self, parent_view, type_key, username):
        super().__init__()
        self.parent_view = parent_view
        self.type_key = type_key
        self.username = username
        current_label = get_config_path(parent_view.cog, username, type_key, "button_label")
        self.label_input = discord.ui.TextInput(
            label="Label Tombol",
            default=current_label,
            style=discord.TextStyle.short,
            max_length=80
        )
        self.add_item(self.label_input)

    async def on_submit(self, interaction: discord.Interaction):
        self.parent_view.cog.config["targets"][self.username]["custom_messages"][self.type_key]["button_label"] = self.label_input.value
        self.parent_view.cog.save_config()
        await interaction.response.edit_message(embed=self.parent_view.build_embed(), view=self.parent_view.build_color_view())

class IgColorInputModal(discord.ui.Modal, title="Atur Warna Custom"):
    def __init__(self, parent_view, type_key, username, color_type):
        super().__init__()
        self.parent_view = parent_view
        self.type_key = type_key
        self.username = username
        self.color_type = color_type
        current_color = get_config_path(parent_view.cog, username, type_key, "embed_color" if color_type == 'embed' else "button_color")
        self.color_input = discord.ui.TextInput(
            label=f"Warna HEX {color_type.capitalize()}",
            default=current_color or "#E1306C",
            style=discord.TextStyle.short,
            max_length=7,
            placeholder="#FFFFFF"
        )
        self.add_item(self.color_input)

    async def on_submit(self, interaction: discord.Interaction):
        color_value = self.color_input.value.strip()
        if not re.match(r'^#[0-9A-Fa-f]{6}$', color_value):
            return await interaction.response.send_message("Format warna HEX tidak valid! Gunakan format: #RRGGBB", ephemeral=True)
        if self.color_type == 'embed':
            self.parent_view.cog.config["targets"][self.username]["custom_messages"][self.type_key]["embed_color"] = color_value
        else:
            self.parent_view.cog.config["targets"][self.username]["custom_messages"][self.type_key]["button_color"] = color_value
        self.parent_view.cog.save_config()
        await interaction.response.edit_message(embed=self.parent_view.build_embed(), view=self.parent_view.build_color_view())

class IgButtonColorView(discord.ui.View):
    def __init__(self, parent_view, type_key, username):
        super().__init__(timeout=180)
        self.parent_view = parent_view
        self.type_key = type_key
        self.username = username
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
            ("Pink IG", "#E1306C"),
            ("Navy", "#34495e")
        ]
        self.add_item(discord.ui.Button(label="WARNA TOMBOL", style=discord.ButtonStyle.grey, disabled=True, row=0))
        for label, style, hex_color in preset_colors:
            button = discord.ui.Button(label=label, style=style, row=1)
            async def callback(interaction: discord.Interaction, btn_style_value, btn_hex):
                config_msg = self.parent_view.cog.config["targets"][self.username]["custom_messages"][self.type_key]
                config_msg["button_style"] = btn_style_value
                config_msg["button_color"] = btn_hex
                self.parent_view.cog.save_config()
                await interaction.response.edit_message(embed=self.parent_view.build_embed(), view=self.parent_view)
                self.stop()
            button.callback = partial(callback, btn_style_value=style.value, btn_hex=hex_color)
            self.add_item(button)
        self.add_item(discord.ui.Button(label="WARNA EMBED", style=discord.ButtonStyle.grey, disabled=True, row=2))
        for label, hex_color in embed_colors[:4]:
            button = discord.ui.Button(label=label, style=discord.ButtonStyle.primary, row=3)
            async def callback(interaction: discord.Interaction, embed_hex):
                config_msg = self.parent_view.cog.config["targets"][self.username]["custom_messages"][self.type_key]
                config_msg["embed_color"] = embed_hex
                self.parent_view.cog.save_config()
                await interaction.response.edit_message(embed=self.parent_view.build_embed(), view=self.parent_view)
                self.stop()
            button.callback = partial(callback, embed_hex=hex_color)
            self.add_item(button)
        for label, hex_color in embed_colors[4:]:
            button = discord.ui.Button(label=label, style=discord.ButtonStyle.primary, row=4)
            async def callback(interaction: discord.Interaction, embed_hex=hex_color):
                config_msg = self.parent_view.cog.config["targets"][self.username]["custom_messages"][self.type_key]
                config_msg["embed_color"] = embed_hex
                self.parent_view.cog.save_config()
                await interaction.response.edit_message(embed=self.parent_view.build_embed(), view=self.parent_view)
                self.stop()
            button.callback = partial(callback, embed_hex=hex_color)
            self.add_item(button)
        custom_embed_btn = discord.ui.Button(label="Custom Warna Embed", style=discord.ButtonStyle.secondary, row=0)
        async def custom_embed_callback(interaction: discord.Interaction):
            await interaction.response.send_modal(IgColorInputModal(self.parent_view, self.type_key, self.username, 'embed'))
        custom_embed_btn.callback = custom_embed_callback
        self.add_item(custom_embed_btn)
        cancel_button = discord.ui.Button(label="Batalkan", style=discord.ButtonStyle.red, row=4)
        async def cancel_callback(interaction: discord.Interaction):
            await interaction.response.edit_message(embed=self.parent_view.build_embed(), view=self.parent_view)
            self.stop()
        cancel_button.callback = cancel_callback
        self.add_item(cancel_button)

class IgMessageConfigView(discord.ui.View):
    def __init__(self, cog, type_key, username):
        super().__init__(timeout=180)
        self.cog = cog
        self.type_key = type_key
        self.username = username

    def build_embed(self):
        target_data = self.cog.config["targets"][self.username]
        config_msg = target_data["custom_messages"][self.type_key]
        embed_color_hex = config_msg.get('embed_color', '#E1306C')
        button_color_hex = config_msg.get('button_color', '#5865f2')
        try:
            color_int = int(embed_color_hex.strip("#"), 16)
            embed_color = discord.Color(color_int)
        except:
            embed_color = discord.Color.blue()
            embed_color_hex = "#E1306C"
        embed = discord.Embed(
            title=f"Pengaturan IG: {self.type_key.upper()}",
            description=f"**Akun Target:** `@{self.username}`",
            color=embed_color
        )
        embed.add_field(name="Isi Pesan Biasa", value=f"`{config_msg.get('content') or 'Belum diatur'}`\n*(Gunakan: {{username}}, {{url}})*", inline=False)
        embed.add_field(name="Judul Embed", value=f"`{config_msg.get('title') or 'Belum diatur'}`", inline=False)
        embed.add_field(name="Deskripsi Embed", value=f"`{config_msg.get('description') or 'Belum diatur'}`", inline=False)
        embed.add_field(name="Label Tombol", value=f"`{config_msg.get('button_label') or 'Belum diatur'}`", inline=False)
        
        button_style_value = config_msg.get('button_style', discord.ButtonStyle.primary.value)
        try:
            button_style_name = discord.ButtonStyle(button_style_value).name.capitalize().replace('_', ' ')
        except ValueError:
            button_style_name = "Primary"
            
        use_embed = config_msg.get('use_embed', True)
        is_tracking = target_data.get("toggles", {}).get(self.type_key, True)

        embed.add_field(name="Style Tombol", value=f"`{button_style_name}`", inline=True)
        embed.add_field(name="Warna Tombol", value=f"`{button_color_hex}`", inline=True)
        embed.add_field(name="Warna Samping Embed", value=f"`{embed_color_hex}`", inline=True)
        embed.add_field(name="Status Embed", value=f"**`{'Aktif' if use_embed else 'Mati'}`**", inline=True)
        embed.add_field(name="Status Tracking", value=f"**`{'Nyala' if is_tracking else 'Mati'}`**", inline=True)
        return embed

    def build_color_view(self):
        return IgButtonColorView(self, self.type_key, self.username)

    @discord.ui.button(label="Atur Pesan Biasa", style=discord.ButtonStyle.secondary, row=0)
    async def set_content_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        current_value = get_config_path(self.cog, self.username, self.type_key, "content")
        await interaction.response.send_modal(IgTextModal("Atur Pesan Biasa", "Isi Pesan", current_value, self, self.type_key, "content", self.username))

    @discord.ui.button(label="Atur Judul Embed", style=discord.ButtonStyle.secondary, row=0)
    async def set_title_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        current_value = get_config_path(self.cog, self.username, self.type_key, "title")
        await interaction.response.send_modal(IgTextModal("Atur Judul Embed", "Judul Embed", current_value, self, self.type_key, "title", self.username))

    @discord.ui.button(label="Atur Deskripsi Embed", style=discord.ButtonStyle.secondary, row=0)
    async def set_desc_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        current_value = get_config_path(self.cog, self.username, self.type_key, "description")
        await interaction.response.send_modal(IgTextModal("Atur Deskripsi Embed", "Deskripsi Embed", current_value, self, self.type_key, "description", self.username))

    @discord.ui.button(label="Atur Tombol & Warna", style=discord.ButtonStyle.secondary, row=1)
    async def set_button_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(IgButtonLabelModal(self, self.type_key, self.username))

    @discord.ui.button(label="Atur Warna Custom", style=discord.ButtonStyle.primary, row=1)
    async def set_custom_color_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(view=self.build_color_view())

    @discord.ui.button(label="Toggle Status Embed", style=discord.ButtonStyle.secondary, row=2)
    async def toggle_embed_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        config_msg = self.cog.config["targets"][self.username]["custom_messages"][self.type_key]
        current_state = config_msg.get('use_embed', True)
        config_msg['use_embed'] = not current_state
        self.cog.save_config()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Toggle Tracking", style=discord.ButtonStyle.danger, row=2)
    async def toggle_tracking_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        toggles = self.cog.config["targets"][self.username].setdefault("toggles", {"post": True, "reel": True, "story": True})
        toggles[self.type_key] = not toggles.get(self.type_key, True)
        self.cog.save_config()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Selesai", style=discord.ButtonStyle.green, row=3)
    async def finish_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.message.delete()
        await interaction.response.send_message("Pengaturan IG Tracker berhasil disimpan!", ephemeral=True, delete_after=5)
        self.stop()

class IgTypeSelectView(discord.ui.View):
    def __init__(self, cog, username):
        super().__init__(timeout=180)
        self.cog = cog
        self.username = username
        options = []
        for key in self.cog.default_messages.keys():
            options.append(discord.SelectOption(label=key.capitalize(), value=key))
        type_select = discord.ui.Select(
            placeholder="Pilih Tipe Konten...",
            options=options,
            custom_id="ig_type_select_menu"
        )
        async def callback(interaction: discord.Interaction):
            selected_type_key = type_select.values[0]
            message_config_view = IgMessageConfigView(self.cog, selected_type_key, self.username)
            await interaction.response.edit_message(content=f"Tipe dipilih: `{selected_type_key}`. Konfigurasi Pesan:", embed=message_config_view.build_embed(), view=message_config_view)
            self.stop()
        type_select.callback = callback
        self.add_item(type_select)
        back_button = discord.ui.Button(label="← Ganti Akun", style=discord.ButtonStyle.secondary, row=1)
        async def back_callback(interaction: discord.Interaction):
            await interaction.response.edit_message(content="Pilih Akun Instagram yang akan dikonfigurasi:", embed=None, view=IgTargetSelectView(self.cog))
            self.stop()
        back_button.callback = back_callback
        self.add_item(back_button)

class IgTargetSelectView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=180)
        self.cog = cog
        self._add_target_select()

    def _get_target_options(self):
        options = []
        for username in self.cog.config.get("targets", {}).keys():
            options.append(discord.SelectOption(label=f"@{username}", value=username))
        return options

    def _add_target_select(self):
        options = self._get_target_options()
        if not options:
            self.add_item(discord.ui.Button(label="Tidak ada akun IG yang dipantau", style=discord.ButtonStyle.red, disabled=True))
            return
        target_select = discord.ui.Select(
            placeholder="Pilih Akun IG...",
            options=options,
            custom_id="ig_target_select_menu"
        )
        async def callback(interaction: discord.Interaction):
            selected_username = target_select.values[0]
            type_select_view = IgTypeSelectView(self.cog, selected_username)
            await interaction.response.edit_message(content=f"Akun dipilih: `@{selected_username}`. Pilih Tipe Konten:", view=type_select_view)
            self.stop()
        target_select.callback = callback
        self.add_item(target_select)

class InstagramTracker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.data_dir = 'data'
        self.config_file = os.path.join(self.data_dir, 'instagram_tracker.json')
        self.api_key = os.getenv("RAPIDAPI_KEY")
        self.mongo_uri = os.getenv("MONGO_URI")
        
        if self.mongo_uri:
            self.mongo_client = MongoClient(self.mongo_uri)
            self.db = self.mongo_client['rtm_database']
            self.collection = self.db['ig_tracker']
        else:
            self.collection = None

        self.default_messages = {
            "post": {
                "title": "[📸 Postingan Baru]({url})",
                "description": "Ada feed baru nih dari @{username}!\n\n{url}",
                "content": "@everyone Update Feed IG!",
                "button_label": "Lihat Postingan",
                "button_style": discord.ButtonStyle.primary.value,
                "button_color": "#E1306C",
                "embed_color": "#E1306C",
                "use_embed": True
            },
            "reel": {
                "title": "[🎥 Reel Baru]({url})",
                "description": "Ada Reel baru dari @{username}!\n\n{url}",
                "content": "@everyone Update Reel IG!",
                "button_label": "Tonton Reel",
                "button_style": discord.ButtonStyle.primary.value,
                "button_color": "#E1306C",
                "embed_color": "#E1306C",
                "use_embed": True
            },
            "story": {
                "title": "[⏱️ Story Baru]({url})",
                "description": "Ada Story baru dari @{username}!\n\n{url}",
                "content": "@everyone Update Story IG!",
                "button_label": "Lihat Story",
                "button_style": discord.ButtonStyle.danger.value,
                "button_color": "#ed4245",
                "embed_color": "#f1c40f",
                "use_embed": True
            }
        }
        
        self.config = self.load_local()

    def load_local(self):
        if not os.path.exists(self.config_file):
            os.makedirs(self.data_dir, exist_ok=True)
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump({"targets": {}}, f, indent=4)
            return {"targets": {}}
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for username, target_data in data.get("targets", {}).items():
                    if "custom_messages" not in target_data:
                        target_data["custom_messages"] = {}
                    if "toggles" not in target_data:
                        target_data["toggles"] = {"post": True, "reel": True, "story": True}
                    for msg_type, default_msg in self.default_messages.items():
                        if msg_type not in target_data["custom_messages"]:
                            target_data["custom_messages"][msg_type] = default_msg.copy()
                return data
        except Exception:
            return {"targets": {}}

    def save_local(self):
        os.makedirs(self.data_dir, exist_ok=True)
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=4)

    def save_config(self):
        self.save_local()
        if self.collection is not None:
            try:
                self.collection.update_one(
                    {"_id": "ig_config"},
                    {"$set": {"targets": self.config.get("targets", {})}},
                    upsert=True
                )
            except Exception:
                pass

    async def cog_load(self):
        if self.collection is not None:
            try:
                data = self.collection.find_one({"_id": "ig_config"})
                if data and "targets" in data:
                    for username, target_data in data["targets"].items():
                        if "custom_messages" not in target_data:
                            target_data["custom_messages"] = {}
                        if "toggles" not in target_data:
                            target_data["toggles"] = {"post": True, "reel": True, "story": True}
                        for msg_type, default_msg in self.default_messages.items():
                            if msg_type not in target_data["custom_messages"]:
                                target_data["custom_messages"][msg_type] = default_msg.copy()
                    self.config["targets"] = data["targets"]
                    self.save_local()
            except Exception:
                pass
        self.monitor_task.start()

    def cog_unload(self):
        self.monitor_task.cancel()

    @commands.command(name='iga')
    @commands.has_permissions(administrator=True)
    async def iga(self, ctx, username: str, channel_input: str = None):
        if channel_input:
            try:
                cid = int(re.sub(r'\D', '', channel_input))
                target_channel = self.bot.get_channel(cid) or await self.bot.fetch_channel(cid)
            except Exception:
                return await ctx.send("Kanal tidak valid.")
        else:
            target_channel = ctx.channel

        if not target_channel:
            return await ctx.send("Kanal tidak ditemukan.")

        targets = self.config.get("targets", {})
        if username not in targets:
            targets[username] = {
                "channels": [],
                "last_post": "",
                "last_story": "",
                "custom_messages": {},
                "toggles": {"post": True, "reel": True, "story": True}
            }
            for msg_type, default_msg in self.default_messages.items():
                targets[username]["custom_messages"][msg_type] = default_msg.copy()

        if target_channel.id not in targets[username]["channels"]:
            targets[username]["channels"].append(target_channel.id)
            self.config["targets"] = targets
            self.save_config()
            await ctx.send(f"Berhasil! @{username} dipantau ke {target_channel.mention} ({target_channel.guild.name})")
        else:
            await ctx.send(f"Akun @{username} sudah ada di daftar kanal tersebut.")

    @commands.command(name='igr')
    @commands.has_permissions(administrator=True)
    async def igr(self, ctx, username: str, channel_input: str = None):
        targets = self.config.get("targets", {})
        if username not in targets:
            return await ctx.send("Akun tidak ditemukan.")

        if channel_input:
            try:
                cid = int(re.sub(r'\D', '', channel_input))
                if cid in targets[username]["channels"]:
                    targets[username]["channels"].remove(cid)
                    if not targets[username]["channels"]:
                        del targets[username]
                    await ctx.send(f"Pantauan @{username} di kanal ID {cid} dihapus.")
                else:
                    await ctx.send("Kanal tersebut tidak memantau akun ini.")
            except:
                return await ctx.send("ID Kanal salah.")
        else:
            del targets[username]
            await ctx.send(f"Hapus total @{username} berhasil.")
        
        self.config["targets"] = targets
        self.save_config()

    @commands.command(name='igl')
    @commands.has_permissions(administrator=True)
    async def igl(self, ctx):
        targets = self.config.get("targets", {})
        if not targets:
            return await ctx.send("Daftar pantauan kosong.")

        embed = discord.Embed(title="Daftar Pantauan Instagram", color=0xE1306C)
        for username, data in targets.items():
            ch_mentions = []
            for cid in data["channels"]:
                ch = self.bot.get_channel(cid)
                if ch:
                    ch_mentions.append(f"{ch.mention} ({ch.guild.name})")
                else:
                    ch_mentions.append(f"`{cid}`")
            
            val = "\n".join(ch_mentions) if ch_mentions else "Tidak ada kanal."
            embed.add_field(name=f"@{username}", value=val, inline=False)
        
        await ctx.send(embed=embed)

    @commands.command(name='ig_config')
    @commands.has_permissions(administrator=True)
    async def start_ig_config(self, ctx):
        targets = self.config.get("targets", {})
        if not targets:
            return await ctx.send("Gagal: Belum ada akun IG yang dipantau. Tambahkan dulu dengan `!iga`.")
        
        view = IgTargetSelectView(self)
        await ctx.send("Pilih Akun Instagram yang akan dikonfigurasi:", view=view)

    @tasks.loop(minutes=20)
    async def monitor_task(self):
        if not self.api_key:
            return

        targets = self.config.get("targets", {})
        if not targets:
            return

        headers = {
            "x-rapidapi-key": self.api_key,
            "x-rapidapi-host": "instagram-scraper-api2.p.rapidapi.com"
        }

        async with aiohttp.ClientSession() as session:
            for username, data in targets.items():
                try:
                    url_posts = "https://instagram-scraper-api2.p.rapidapi.com/v1/user_posts"
                    params = {"username_or_id_or_url": username}
                    async with session.get(url_posts, headers=headers, params=params) as resp:
                        if resp.status == 200:
                            res_json = await resp.json()
                            items = res_json.get("data", {}).get("items", [])
                            if items:
                                latest = items[0]
                                post_id = latest.get("id")
                                
                                if post_id and post_id != data.get("last_post"):
                                    data["last_post"] = post_id
                                    self.config["targets"][username] = data
                                    self.save_config()
                                    
                                    code = latest.get("code")
                                    post_url = f"https://www.instagram.com/p/{code}/"
                                    
                                    direct_media_url = None
                                    is_video = False
                                    
                                    if "video_versions" in latest and latest["video_versions"]:
                                        direct_media_url = latest["video_versions"][0].get("url")
                                        is_video = True
                                    elif "carousel_media" in latest and latest["carousel_media"]:
                                        first_item = latest["carousel_media"][0]
                                        if "video_versions" in first_item and first_item["video_versions"]:
                                            direct_media_url = first_item["video_versions"][0].get("url")
                                            is_video = True
                                        elif "image_versions2" in first_item and first_item["image_versions2"].get("candidates"):
                                            direct_media_url = first_item["image_versions2"]["candidates"][0].get("url")
                                    elif "image_versions2" in latest and latest["image_versions2"].get("candidates"):
                                        direct_media_url = latest["image_versions2"]["candidates"][0].get("url")

                                    content_type = "reel" if is_video else "post"
                                    is_tracked = data.get("toggles", {}).get(content_type, True)
                                    
                                    if is_tracked:
                                        config_msg = data["custom_messages"].get(content_type, self.default_messages[content_type])
                                        await self._send_notification(username, data["channels"], post_url, direct_media_url, is_video, config_msg)

                    url_stories = "https://instagram-scraper-api2.p.rapidapi.com/v1/user_stories"
                    async with session.get(url_stories, headers=headers, params=params) as resp_st:
                        if resp_st.status == 200:
                            res_json_st = await resp_st.json()
                            items_st = res_json_st.get("data", {}).get("items", [])
                            if items_st:
                                latest_story = sorted(items_st, key=lambda x: x.get('taken_at', 0), reverse=True)[0]
                                story_id = latest_story.get("pk")
                                
                                if story_id and str(story_id) != str(data.get("last_story")):
                                    data["last_story"] = str(story_id)
                                    self.config["targets"][username] = data
                                    self.save_config()
                                    
                                    story_url = f"https://www.instagram.com/stories/{username}/{story_id}/"
                                    
                                    direct_media_url_st = None
                                    is_video_st = False
                                    
                                    if "video_versions" in latest_story and latest_story["video_versions"]:
                                        direct_media_url_st = latest_story["video_versions"][0].get("url")
                                        is_video_st = True
                                    elif "image_versions2" in latest_story and latest_story["image_versions2"].get("candidates"):
                                        direct_media_url_st = latest_story["image_versions2"]["candidates"][0].get("url")

                                    is_tracked_st = data.get("toggles", {}).get("story", True)
                                    if is_tracked_st:
                                        config_msg_st = data["custom_messages"].get("story", self.default_messages["story"])
                                        await self._send_notification(username, data["channels"], story_url, direct_media_url_st, is_video_st, config_msg_st)

                except Exception as e:
                    pass
                await asyncio.sleep(5)

    async def _send_notification(self, username, channels, url, direct_media_url, is_video, config_msg):
        msg_content = config_msg.get('content', '')
        embed_title = config_msg.get('title', '')
        embed_desc = config_msg.get('description', '')
        use_embed = config_msg.get('use_embed', True)

        if msg_content:
            msg_content = msg_content.replace("{username}", username).replace("{url}", url)
        if embed_title:
            embed_title = embed_title.replace("{username}", username).replace("{url}", url)
        if embed_desc:
            embed_desc = embed_desc.replace("{username}", username).replace("{url}", url)

        embed_obj = None
        if use_embed:
            embed_color_hex = config_msg.get('embed_color', '#E1306C')
            try:
                embed_color = discord.Color(int(embed_color_hex.strip("#"), 16))
            except:
                embed_color = discord.Color.blue()
                
            embed_obj = discord.Embed(title=embed_title, description=embed_desc, color=embed_color)
            if direct_media_url and not is_video:
                embed_obj.set_image(url=direct_media_url)
        else:
            if msg_content:
                msg_content += f"\n{url}"
            else:
                msg_content = url

        if is_video and direct_media_url:
            if msg_content:
                msg_content += f"\n👇 **[Putar Video Langsung]({direct_media_url})**"
            else:
                msg_content = f"👇 **[Putar Video Langsung]({direct_media_url})**"

        button_label = config_msg.get('button_label', 'Buka Instagram')
        button_style_value = config_msg.get('button_style', discord.ButtonStyle.primary.value)
        try:
            button_style = discord.ButtonStyle(button_style_value)
        except ValueError:
            button_style = discord.ButtonStyle.primary

        view = discord.ui.View()
        button = discord.ui.Button(label=button_label, style=button_style, url=url)
        view.add_item(button)

        for channel_id in channels:
            target_ch = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
            if target_ch:
                try:
                    await target_ch.send(content=msg_content, embed=embed_obj, view=view)
                except Exception:
                    pass

    @monitor_task.before_loop
    async def before_monitor_task(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(InstagramTracker(bot))
