import discord
from discord.ext import commands, tasks
import json
import os
import asyncio
import aiohttp
import logging
import re
from pymongo import MongoClient

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

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

        self.config = self.load_local()

    def load_local(self):
        if not os.path.exists(self.config_file):
            os.makedirs(self.data_dir, exist_ok=True)
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump({"targets": {}}, f, indent=4)
            return {"targets": {}}
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
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
                "last_post": ""
            }

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
                    url = "https://instagram-scraper-api2.p.rapidapi.com/v1/user_posts"
                    params = {"username_or_id_or_url": username}
                    async with session.get(url, headers=headers, params=params) as resp:
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

                                    msg_body = f"**🌟 Update Baru dari @{username}!**\n🔗 [Buka di Instagram]({post_url})"
                                    embed_obj = None
                                    
                                    if is_video and direct_media_url:
                                        msg_body += f"\n👇 **[Putar Video Langsung]({direct_media_url})**"
                                    elif direct_media_url:
                                        embed_obj = discord.Embed(color=0xE1306C)
                                        embed_obj.set_image(url=direct_media_url)
                                    
                                    for channel_id in data["channels"]:
                                        target_ch = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
                                        if target_ch:
                                            try:
                                                await target_ch.send(content=msg_body, embed=embed_obj)
                                            except:
                                                pass
                except:
                    pass
                await asyncio.sleep(5)

    @monitor_task.before_loop
    async def before_monitor_task(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(InstagramTracker(bot))
