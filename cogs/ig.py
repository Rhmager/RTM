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

class IgColorInputModal(discord.ui.Modal, title="Atur Warna Custom"):
    def __init__(self, parent_view, type_key, username):
        super().__init__()
        self.parent_view = parent_view
        self.type_key = type_key
        self.username = username
        
        target_data = parent_view.cog.config["targets"].get(username)
        path = target_data["custom_messages"][type_key] if target_data else {}
        current_color = path.get("embed_color", "")
        
        self.color_input = discord.ui.TextInput(
            label="Warna HEX Embed",
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
        self.parent_view.cog.config["targets"][self.username]["custom_messages"][self.type_key]["embed_color"] = color_value
        self.parent_view.cog.save_config()
        await interaction.response.edit_message(embed=self.parent_view.build_embed(), view=self.parent_view.build_color_view())

class IgEmbedColorView(discord.ui.View):
    def __init__(self, parent_view, type_key, username):
        super().__init__(timeout=180)
        self.parent_view = parent_view
        self.type_key = type_key
        self.username = username
        self._create_buttons()

    def _create_buttons(self):
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
        
        self.add_item(discord.ui.Button(label="WARNA EMBED", style=discord.ButtonStyle.grey, disabled=True, row=0))
        
        for label, hex_color in embed_colors[:4]:
            button = discord.ui.Button(label=label, style=discord.ButtonStyle.primary, row=1)
            async def callback(interaction: discord.Interaction, embed_hex):
                config_msg = self.parent_view.cog.config["targets"][self.username]["custom_messages"][self.type_key]
                config_msg["embed_color"] = embed_hex
                self.parent_view.cog.save_config()
                await interaction.response.edit_message(embed=self.parent_view.build_embed(), view=self.parent_view)
                self.stop()
            button.callback = partial(callback, embed_hex=hex_color)
            self.add_item(button)
            
        for label, hex_color in embed_colors[4:]:
            button = discord.ui.Button(label=label, style=discord.ButtonStyle.primary, row=2)
            async def callback(interaction: discord.Interaction, embed_hex=hex_color):
                config_msg = self.parent_view.cog.config["targets"][self.username]["custom_messages"][self.type_key]
                config_msg["embed_color"] = embed_hex
                self.parent_view.cog.save_config()
                await interaction.response.edit_message(embed=self.parent_view.build_embed(), view=self.parent_view)
                self.stop()
            button.callback = partial(callback, embed_hex=hex_color)
            self.add_item(button)
            
        custom_embed_btn = discord.ui.Button(label="Custom Warna Embed", style=discord.ButtonStyle.secondary, row=3)
        async def custom_embed_callback(interaction: discord.Interaction):
            await interaction.response.send_modal(IgColorInputModal(self.parent_view, self.type_key, self.username))
        custom_embed_btn.callback = custom_embed_callback
        self.add_item(custom_embed_btn)
        
        cancel_button = discord.ui.Button(label="Batalkan", style=discord.ButtonStyle.red, row=3)
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
        
        use_embed = config_msg.get('use_embed', True)
        is_tracking = target_data.get("toggles", {}).get(self.type_key, True)
        show_ig_link = config_msg.get('show_ig_link', True)

        embed.add_field(name="Warna Samping Embed", value=f"`{embed_color_hex}`", inline=True)
        embed.add_field(name="Status Embed", value=f"**`{'Aktif' if use_embed else 'Mati'}`**", inline=True)
        embed.add_field(name="Tampil Link IG Asli", value=f"**`{'Ya' if show_ig_link else 'Tidak'}`**", inline=True)
        embed.add_field(name="Status Tracking", value=f"**`{'Nyala' if is_tracking else 'Mati'}`**", inline=True)
        return embed

    def build_color_view(self):
        return IgEmbedColorView(self, self.type_key, self.username)

    @discord.ui.button(label="Atur Pesan", style=discord.ButtonStyle.secondary, row=0)
    async def set_content_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        target_data = self.cog.config["targets"].get(self.username)
        path = target_data["custom_messages"][self.type_key] if target_data else {}
        current_value = path.get("content", "")
        await interaction.response.send_modal(IgTextModal("Atur Pesan Biasa", "Isi Pesan", current_value, self, self.type_key, "content", self.username))

    @discord.ui.button(label="Atur Judul", style=discord.ButtonStyle.secondary, row=0)
    async def set_title_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        target_data = self.cog.config["targets"].get(self.username)
        path = target_data["custom_messages"][self.type_key] if target_data else {}
        current_value = path.get("title", "")
        await interaction.response.send_modal(IgTextModal("Atur Judul Embed", "Judul Embed", current_value, self, self.type_key, "title", self.username))

    @discord.ui.button(label="Atur Deskripsi", style=discord.ButtonStyle.secondary, row=0)
    async def set_desc_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        target_data = self.cog.config["targets"].get(self.username)
        path = target_data["custom_messages"][self.type_key] if target_data else {}
        current_value = path.get("description", "")
        await interaction.response.send_modal(IgTextModal("Atur Deskripsi Embed", "Deskripsi Embed", current_value, self, self.type_key, "description", self.username))

    @discord.ui.button(label="Warna Embed", style=discord.ButtonStyle.primary, row=1)
    async def set_custom_color_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(view=self.build_color_view())

    @discord.ui.button(label="Toggle Embed", style=discord.ButtonStyle.secondary, row=1)
    async def toggle_embed_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        config_msg = self.cog.config["targets"][self.username]["custom_messages"][self.type_key]
        current_state = config_msg.get('use_embed', True)
        config_msg['use_embed'] = not current_state
        self.cog.save_config()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Toggle Link IG", style=discord.ButtonStyle.secondary, row=1)
    async def toggle_ig_link_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        config_msg = self.cog.config["targets"][self.username]["custom_messages"][self.type_key]
        current_state = config_msg.get('show_ig_link', True)
        config_msg['show_ig_link'] = not current_state
        self.cog.save_config()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Toggle Tracking", style=discord.ButtonStyle.danger, row=1)
    async def toggle_tracking_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        toggles = self.cog.config["targets"][self.username].setdefault("toggles", {"post": True, "reel": True, "story": True})
        toggles[self.type_key] = not toggles.get(self.type_key, True)
        self.cog.save_config()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Selesai", style=discord.ButtonStyle.green, row=2)
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
        back_button = discord.ui.Button(label="Ganti Akun", style=discord.ButtonStyle.secondary, row=1)
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
        self.config_db_key = "data/instagram_tracker.json"
        self.api_key = os.getenv("RAPIDAPI_KEY")
        self.mongo_uri = os.getenv("MONGODB_URI")
        self.collection = None

        if self.mongo_uri:
            try:
                self.mongo_client = MongoClient(self.mongo_uri, serverSelectionTimeoutMS=5000)
                self.db = self.mongo_client["reSwan"]
                self.collection = self.db["Data collection"]
            except Exception as e:
                logging.error(f"IG Tracker MongoDB Error: {e}")
        
        self.default_messages = {
            "post": {
                "title": "[Postingan Baru]({url})",
                "description": "Ada feed baru nih dari @{username}!\n\n{url}",
                "content": "@everyone Update Feed IG!",
                "embed_color": "#E1306C",
                "use_embed": True,
                "show_ig_link": True
            },
            "reel": {
                "title": "[Reel Baru]({url})",
                "description": "Ada Reel baru dari @{username}!\n\n{url}",
                "content": "@everyone Update Reel IG!",
                "embed_color": "#E1306C",
                "use_embed": True,
                "show_ig_link": True
            },
            "story": {
                "title": "[Story Baru]({url})",
                "description": "Ada Story baru dari @{username}!\n\n{url}",
                "content": "@everyone Update Story IG!",
                "embed_color": "#f1c40f",
                "use_embed": True,
                "show_ig_link": True
            }
        }
        
        self.config = {"targets": {}}
        self.load_data()
        self.monitor_task.start()

    def cog_unload(self):
        self.monitor_task.cancel()

    def load_data(self):
        loaded_from_mongo = False
        if self.collection is not None:
            try:
                stored = self.collection.find_one({"_id": "latest_backup"})
                if stored and "backup" in stored:
                    backup_dict = stored["backup"]
                    ig_data = backup_dict.get(self.config_db_key) or backup_dict.get(self.config_db_key.replace('/', '\\'))
                    if ig_data:
                        self.config = ig_data
                        loaded_from_mongo = True
                        logging.info("IG Tracker: Config diload dari MongoDB.")
            except Exception as e:
                logging.error(f"IG Tracker gagal load Mongo: {e}")

        if not loaded_from_mongo:
            if os.path.exists(self.config_file):
                try:
                    with open(self.config_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        if "targets" in data:
                            self.config["targets"] = data["targets"]
                except Exception:
                    pass
            else:
                os.makedirs(self.data_dir, exist_ok=True)

        for username, target_data in self.config.setdefault("targets", {}).items():
            if "custom_messages" not in target_data:
                target_data["custom_messages"] = {}
            if "toggles" not in target_data:
                target_data["toggles"] = {"post": True, "reel": True, "story": True}
            if "recent_posts" not in target_data:
                target_data["recent_posts"] = []
            if "recent_stories" not in target_data:
                target_data["recent_stories"] = []
            for msg_type, default_msg in self.default_messages.items():
                if msg_type not in target_data["custom_messages"]:
                    target_data["custom_messages"][msg_type] = default_msg.copy()
                if "show_ig_link" not in target_data["custom_messages"][msg_type]:
                    target_data["custom_messages"][msg_type]["show_ig_link"] = True
        
        self.save_local()

    def save_local(self):
        os.makedirs(self.data_dir, exist_ok=True)
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
        except Exception:
            pass

    def save_config(self):
        self.save_local()
        if self.collection is not None:
            try:
                self.collection.update_one(
                    {"_id": "latest_backup"},
                    {"$set": {f"backup.{self.config_db_key}": self.config}},
                    upsert=True
                )
            except Exception:
                pass

    @commands.command(name='iga')
    @commands.has_permissions(administrator=True)
    async def iga(self, ctx, username: str, channel_input: str = None):
        username = username.replace('@', '').strip()
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
                "recent_posts": [],
                "recent_stories": [],
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
        username = username.replace('@', '').strip()
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

    def _parse_items(self, res_json):
        items = []
        if "result" in res_json:
            if isinstance(res_json["result"], dict) and "edges" in res_json["result"]:
                for edge in res_json["result"]["edges"]:
                    node = edge.get("node", {})
                    items.append(node.get("media", node))
            elif isinstance(res_json["result"], list):
                items = res_json["result"]
        elif "data" in res_json:
            if isinstance(res_json["data"], list):
                items = res_json["data"]
            elif isinstance(res_json["data"], dict) and "items" in res_json["data"]:
                items = res_json["data"]["items"]
        elif isinstance(res_json, list):
            items = res_json
        return items

    def _get_timestamp(self, item):
        ts = item.get("taken_at") or item.get("taken_at_timestamp") or item.get("device_timestamp")
        if ts:
            try: return int(ts)
            except: pass
            
        caption = item.get("caption")
        if isinstance(caption, dict):
            c_ts = caption.get("created_at")
            if c_ts:
                try: return int(c_ts)
                except: pass
                
        return 0

    async def _fetch_and_process(self, session, url, headers, payload, username, data, content_type_target):
        for attempt in range(3):
            try:
                async with session.post(url, headers=headers, json=payload) as resp:
                    if resp.status == 200:
                        res_json = await resp.json()
                        items = self._parse_items(res_json)
                        
                        items.reverse()
                        items.sort(key=self._get_timestamp)
                        
                        is_story = (content_type_target == "story")
                        recent_key = "recent_stories" if is_story else "recent_posts"
                        is_first_fetch = len(data[recent_key]) == 0
                        new_count = 0

                        for item in items:
                            raw_id = str(item.get("pk", item.get("id", "")))
                            if not raw_id:
                                continue
                                
                            item_id = raw_id.split("_")[0] if "_" in raw_id else raw_id
                            
                            if item_id in data[recent_key]:
                                continue
                            
                            data[recent_key].append(item_id)
                            if len(data[recent_key]) > 999:
                                data[recent_key].pop(0)
                            self.config["targets"][username] = data
                            self.save_config()
                            
                            new_count += 1
                            
                            if is_first_fetch and item != items[-1]:
                                continue

                            code = item.get("code", item.get("shortcode", ""))
                            if is_story:
                                item_url = f"https://www.instagram.com/stories/{username}/{item_id}/"
                            else:
                                item_url = f"https://www.instagram.com/p/{code}/" if code else f"https://www.instagram.com/{username}/"
                            
                            direct_media_url = None
                            is_video = item.get("is_video", False)
                            
                            if not direct_media_url and "carousel_media" in item:
                                children = item["carousel_media"]
                                if children:
                                    first_child = children[0]
                                    if first_child.get("video_versions"):
                                        direct_media_url = first_child["video_versions"][0].get("url")
                                        is_video = True
                                    elif first_child.get("image_versions2") and first_child["image_versions2"].get("candidates"):
                                        direct_media_url = first_child["image_versions2"]["candidates"][0].get("url")

                            if not direct_media_url and "edge_sidecar_to_children" in item:
                                children = item["edge_sidecar_to_children"].get("edges", [])
                                if children:
                                    for child_edge in children:
                                        child = child_edge.get("node", {})
                                        if child.get("is_video") and child.get("video_url"):
                                            direct_media_url = child.get("video_url")
                                            is_video = True
                                            break
                                        elif child.get("display_url") and not direct_media_url:
                                            direct_media_url = child.get("display_url")
                            
                            if not direct_media_url:
                                if item.get("video_url"):
                                    direct_media_url = item.get("video_url")
                                    is_video = True
                                elif "video_versions" in item and item["video_versions"]:
                                    direct_media_url = item["video_versions"][0].get("url")
                                    is_video = True
                                elif item.get("display_url"):
                                    direct_media_url = item.get("display_url")
                                elif "image_versions2" in item and item["image_versions2"].get("candidates"):
                                    direct_media_url = item["image_versions2"]["candidates"][0].get("url")

                            actual_content_type = "reel" if (is_video and not is_story) else content_type_target
                            
                            is_tracked = data.get("toggles", {}).get(actual_content_type, True)
                            if is_tracked:
                                config_msg = data["custom_messages"].get(actual_content_type, self.default_messages[actual_content_type])
                                await self._send_notification(username, data["channels"], item_url, direct_media_url, is_video, config_msg)
                        
                        if new_count > 0:
                            logging.info(f"IG Tracker: Menemukan {new_count} {content_type_target} baru untuk @{username}.")
                        return
                    elif resp.status >= 500:
                        logging.warning(f"IG Tracker: HTTP {resp.status} dari {url}. Mencoba ulang...")
                        await asyncio.sleep(5)
                    else:
                        logging.error(f"IG Tracker: HTTP {resp.status} dari {url} untuk @{username}.")
                        return
            except Exception as e:
                logging.error(f"IG Tracker: Exception pada {url} untuk @{username}: {e}")
                await asyncio.sleep(5)

    @tasks.loop(minutes=20)
    async def monitor_task(self):
        if not self.api_key:
            logging.error("IG Tracker: RAPIDAPI_KEY kosong! Tidak bisa menjalankan monitor_task.")
            return

        targets = self.config.get("targets", {})
        if not targets:
            return

        headers = {
            "x-rapidapi-key": self.api_key,
            "x-rapidapi-host": "instagram120.p.rapidapi.com",
            "Content-Type": "application/json"
        }

        async with aiohttp.ClientSession() as session:
            for username, data in targets.items():
                username = username.replace('@', '').strip()
                
                if "recent_posts" not in data: data["recent_posts"] = []
                if "recent_stories" not in data: data["recent_stories"] = []

                track_post = data.get("toggles", {}).get("post", True)
                track_reel = data.get("toggles", {}).get("reel", True)
                
                if track_post or track_reel:
                    payload = {"username": username, "maxId": ""}
                    url = "https://instagram120.p.rapidapi.com/api/instagram/posts"
                    await self._fetch_and_process(session, url, headers, payload, username, data, "post")

                if data.get("toggles", {}).get("story", True):
                    payload = {"username": username}
                    url = "https://instagram120.p.rapidapi.com/api/instagram/stories"
                    await self._fetch_and_process(session, url, headers, payload, username, data, "story")
                
                await asyncio.sleep(5)

    async def _send_notification(self, username, channels, url, direct_media_url, is_video, config_msg):
        msg_content = config_msg.get('content', '')
        embed_title = config_msg.get('title', '')
        embed_desc = config_msg.get('description', '')
        use_embed = config_msg.get('use_embed', True)
        show_ig_link = config_msg.get('show_ig_link', True)

        ig_url_text = url if show_ig_link else ""

        if msg_content:
            msg_content = msg_content.replace("{username}", username).replace("{url}", ig_url_text)
        if embed_title:
            embed_title = embed_title.replace("{username}", username).replace("{url}", ig_url_text)
        if embed_desc:
            embed_desc = embed_desc.replace("{username}", username).replace("{url}", ig_url_text)

        if not show_ig_link:
            embed_title = re.sub(r'\[(.*?)\]\(\s*\)', r'\1', embed_title).strip()

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
            if not msg_content:
                msg_content = url if show_ig_link else ""
            elif show_ig_link and "{url}" not in config_msg.get('content', ''):
                msg_content += f"\n{url}"

        if direct_media_url:
            direct_text = f"\n👇 [Putar Video Langsung]({direct_media_url})" if is_video else f"\n👇 [Lihat Foto Langsung]({direct_media_url})"
            if msg_content:
                msg_content += direct_text
            else:
                msg_content = direct_text.strip()

        for channel_id in channels:
            target_ch = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
            if target_ch:
                try:
                    await target_ch.send(content=msg_content, embed=embed_obj)
                except Exception:
                    pass

    @monitor_task.before_loop
    async def before_monitor_task(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(InstagramTracker(bot))
