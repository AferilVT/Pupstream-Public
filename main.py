import discord
from discord import slash_command
import dotenv
from discord.ext import commands, tasks
import requests
import json
import os
from datetime import datetime
import asyncio

dotenv.load_dotenv()

# Load configurations
with open('streamers.json', 'r') as f:
    config = json.load(f)

with open('custom_messages.json', 'r') as f:
    custom_messages = json.load(f)

# Bot configuration
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')  # Replace with your Discord bot token
TWITCH_CLIENT_ID = os.getenv('TWITCH_CLIENT_ID')  # Replace with your Twitch client ID
TWITCH_CLIENT_SECRET = os.getenv('TWITCH_CLIENT_SECRET')  # Replace with your Twitch client secret

# Channel IDs - Replace these with your actual channel IDs
GENERAL_NOTIFICATION_CHANNEL_ID = {ChannelIDHere}  # Replace with your general notification channel ID
MAIN_NOTIFICATION_CHANNEL_ID = {ChannelIDHere}  # Replace with main notification channel ID

MOD_ROLE_ID = {ModeratorRoleIdHere}

# Initialize bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Store stream status
stream_status = {}

def save_configs():
    with open('streamers.json', 'w') as f:
        json.dump(config, f, indent=2)
    with open('custom_messages.json', 'w') as f:
        json.dump(custom_messages, f, indent=2)

async def get_twitch_access_token():
    url = 'https://id.twitch.tv/oauth2/token'
    params = {
        'client_id': TWITCH_CLIENT_ID,
        'client_secret': TWITCH_CLIENT_SECRET,
        'grant_type': 'client_credentials'
    }
    response = requests.post(url, params=params)
    return response.json()['access_token']

async def get_stream_details(streamer):
    access_token = await get_twitch_access_token()
    headers = {
        'Client-ID': TWITCH_CLIENT_ID,
        'Authorization': f'Bearer {access_token}'
    }
    # Get stream info
    stream_url = f'https://api.twitch.tv/helix/streams?user_login={streamer}'
    stream_resp = requests.get(stream_url, headers=headers)
    stream_data = stream_resp.json()['data']
    if not stream_data:
        return None
    stream = stream_data[0]
    # Get user info
    user_url = f'https://api.twitch.tv/helix/users?login={streamer}'
    user_resp = requests.get(user_url, headers=headers)
    user = user_resp.json()['data'][0]
    # Get game info
    game_name = "Unknown"
    if stream.get('game_id'):
        game_url = f'https://api.twitch.tv/helix/games?id={stream["game_id"]}'
        game_resp = requests.get(game_url, headers=headers)
        game_data = game_resp.json()['data']
        if game_data:
            game_name = game_data[0]['name']
    # Prepare details
    return {
        'title': stream['title'],
        'game': game_name,
        'viewers': stream['viewer_count'],
        'thumbnail': stream['thumbnail_url'].replace('{width}', '640').replace('{height}', '360') + f'?rand={int(datetime.utcnow().timestamp())}',
        'profile_image': user['profile_image_url'],
        'display_name': user['display_name'],
        'login': user['login']
    }

@tasks.loop(minutes=2)
async def check_streams():
    for streamer in config['streamers']:
        details = await get_stream_details(streamer)
        is_live = details is not None
        # If streamer just went live
        if is_live and streamer not in stream_status:
            stream_status[streamer] = True
            # Create embed for notification
            embed = discord.Embed(
                description=details['title'],
                color=discord.Color.purple(),
                timestamp=datetime.utcnow()
            )
            embed.set_author(
                name=f"{details['display_name']} is now live on Twitch!",
                url=f"https://twitch.tv/{details['login']}",
                icon_url=details['profile_image']
            )
            embed.add_field(name="Game", value=details['game'], inline=True)
            embed.add_field(name="Viewers", value=details['viewers'], inline=True)
            embed.set_image(url=details['thumbnail'])
            embed.set_footer(text="twitch.tv", icon_url="https://static.twitchcdn.net/assets/favicon-32-e29e246c157142c94346.png")
            
            # Get custom message if exists
            custom_message = custom_messages['custom_messages'].get(streamer.lower(), f"{details['display_name']} is now live!")
            
            # Send notification to appropriate channel
            if streamer.lower() == "shieorie":
                channel = bot.get_channel(MAIN_NOTIFICATION_CHANNEL_ID)
                if channel:
                    await channel.send(f"@everyone {custom_message}", embed=embed)
            else:
                channel = bot.get_channel(GENERAL_NOTIFICATION_CHANNEL_ID)
                if channel:
                    await channel.send(custom_message, embed=embed)
        
        # If streamer went offline
        elif not is_live and streamer in stream_status:
            del stream_status[streamer]

@bot.event
async def on_ready():
    print(f'Bot is ready! Logged in as {bot.user.name}')
    check_streams.start()

    await bot.change_presence(
        activity=discord.Game(name="with my code")
    )

def is_owner_or_mod(ctx):
    # Allow server owner
    if ctx.author.id == ctx.guild.owner_id:
        return True
    # Allow users with the moderator role
    mod_role = discord.utils.get(ctx.author.roles, id=MOD_ROLE_ID)
    return mod_role is not None

class StreamerCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @slash_command(name="add", description="Add a new streamer to monitor")
    async def add_streamer(self, ctx, streamer: str):
        if not is_owner_or_mod(ctx):
            await ctx.respond("You do not have permission to use this command.", ephemeral=True)
            return
        if streamer.lower() in [s.lower() for s in config['streamers']]:
            await ctx.respond(f"Streamer {streamer} is already being monitored!", ephemeral=True)
            return
        
        # Verify streamer exists on Twitch
        access_token = await get_twitch_access_token()
        headers = {
            'Client-ID': TWITCH_CLIENT_ID,
            'Authorization': f'Bearer {access_token}'
        }
        user_url = f'https://api.twitch.tv/helix/users?login={streamer}'
        user_resp = requests.get(user_url, headers=headers)
        user_data = user_resp.json()['data']
        
        if not user_data:
            await ctx.respond(f"Streamer {streamer} not found on Twitch!", ephemeral=True)
            return
        
        config['streamers'].append(streamer)
        save_configs()
        await ctx.respond(f"Added {streamer} to monitored streamers!", ephemeral=True)

    @slash_command(name="remove", description="Remove a streamer from monitoring")
    async def remove_streamer(self, ctx, streamer: str):
        if not is_owner_or_mod(ctx):
            await ctx.respond("You do not have permission to use this command.", ephemeral=True)
            return
        if streamer.lower() not in [s.lower() for s in config['streamers']]:
            await ctx.respond(f"Streamer {streamer} is not being monitored!", ephemeral=True)
            return
        
        config['streamers'] = [s for s in config['streamers'] if s.lower() != streamer.lower()]
        if streamer.lower() in custom_messages['custom_messages']:
            del custom_messages['custom_messages'][streamer.lower()]
        save_configs()
        await ctx.respond(f"Removed {streamer} from monitored streamers!", ephemeral=True)

    @slash_command(name="setmessage", description="Set a custom going live message for a streamer")
    async def set_message(self, ctx, streamer: str, message: str):
        if not is_owner_or_mod(ctx):
            await ctx.respond("You do not have permission to use this command.", ephemeral=True)
            return
        if streamer.lower() not in [s.lower() for s in config['streamers']]:
            await ctx.respond(f"Streamer {streamer} is not being monitored!", ephemeral=True)
            return
        
        custom_messages['custom_messages'][streamer.lower()] = message
        save_configs()
        await ctx.respond(f"Set custom message for {streamer}!\nMessage: {message}", ephemeral=True)

    @slash_command(name="list", description="List all monitored streamers")
    async def list_streamers(self, ctx):
        if not is_owner_or_mod(ctx):
            await ctx.respond("You do not have permission to use this command.", ephemeral=True)
            return
        streamers_list = "\n".join([f"• {s}" for s in config['streamers']])
        await ctx.respond(f"Monitored streamers:\n{streamers_list}", ephemeral=True)

# Add the cog to the bot
bot.add_cog(StreamerCommands(bot))

# Run the bot
if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
