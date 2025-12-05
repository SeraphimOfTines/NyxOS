import logging
import asyncio
from aiohttp import web
import json
import config

logger = logging.getLogger('NyxAPI')

class NyxAPI:
    def __init__(self, bot_client):
        self.bot = bot_client
        self.app = web.Application()
        self.port = config.CONTROL_API_PORT
        self.api_key = config.CONTROL_API_KEY
        
        # Middleware / Auth
        self.app.middlewares.append(self.auth_middleware)
        
        # Routes
        self.app.router.add_get('/api/status', self.handle_status)
        self.app.router.add_get('/api/bars', self.handle_get_bars)
        self.app.router.add_post('/api/global/update', self.handle_global_update)
        self.app.router.add_post('/api/global/state', self.handle_global_state)
        self.app.router.add_post('/api/bar/{channel_id}/update', self.handle_bar_update)
        self.app.router.add_get('/api/emojis', self.handle_get_emojis)
        
        self.runner = None
        self.site = None

    async def auth_middleware(self, app, handler):
        async def middleware_handler(request):
            # Allow simple CORS for local development if needed, or strict checking
            provided_key = request.headers.get('x-api-key')
            if provided_key != self.api_key:
                return web.json_response({'error': 'Unauthorized'}, status=401)
            return await handler(request)
        return middleware_handler

    async def start(self):
        """Starts the web server."""
        self.runner = web.AppRunner(self.app, access_log=None)
        await self.runner.setup()
        # Listen on 0.0.0.0 to allow remote connections (protected by Key)
        self.site = web.TCPSite(self.runner, '0.0.0.0', self.port)
        await self.site.start()
        logger.info(f"NyxAPI Server started on port {self.port}")

    async def stop(self):
        """Stops the web server."""
        if self.site:
            await self.runner.cleanup()

    # --- Handlers ---

    async def handle_status(self, request):
        """Returns bot health and status."""
        return web.json_response({
            'status': 'online',
            'latency': round(self.bot.latency * 1000, 2),
            'user': str(self.bot.user),
            'id': self.bot.user.id
        })

    async def handle_get_emojis(self, request):
        """Returns a list of all custom emojis visible to the bot, filtered by Guild ID."""
        emojis_data = []
        for emoji in self.bot.emojis:
            # Filter: Only allow emojis from the configured Temple Guild
            # (TEMPLE_GUILD_ID defaults to 411597692037496833)
            if emoji.guild.id != config.TEMPLE_GUILD_ID:
                continue

            # Format: <a:Name:ID> or <:Name:ID>
            animated_tag = "a" if emoji.animated else ""
            full_str = f"<{animated_tag}:{emoji.name}:{emoji.id}>"
            
            emojis_data.append({
                "name": emoji.name,
                "id": str(emoji.id),
                "string": full_str,
                "animated": emoji.animated,
                "url": str(emoji.url)
            })
            
        return web.json_response({'emojis': emojis_data, 'count': len(emojis_data)})

    async def handle_get_bars(self, request):
        """Returns a list of all active status bars."""
        bars_data = []
        
        # We need to iterate safely over the active_bars dictionary
        # Structure of active_bars is {channel_id: message_id}
        # We need to fetch the actual channel/message objects to get content
        
        # Optimization: Using internal cache where possible to avoid API spam
        for channel_id, message_id in self.bot.active_bars.items():
            channel = self.bot.get_channel(channel_id)
            if not channel:
                continue
            
            # Try to get category
            category = channel.category.name if channel.category else "Uncategorized"
            
            # For content, we ideally want the cached message content
            # But messages might not be in cache. 
            # For the V1 of this API, we will use a placeholder or last known state
            # if we can't easily access the message without an API call.
            # However, the GUI needs the content. 
            
            # Let's check the message cache
            message = None
            # discord.py's get_message is for cache lookup
            # fetch_message is API call (async)
            
            # CAUTION: Doing fetch_message for ALL bars on every refresh is a bad idea (Rate Limits).
            # We should rely on what the bot 'thinks' the Master Bar content is, 
            # or potentially store the content in the active_bars dict in the future.
            
            # For now, we return the channel metadata. The GUI might have to rely on the 
            # Master Bar content for the 'text' part, and the user just toggles icons.
            
            bars_data.append({
                'channel_id': str(channel_id),
                'channel_name': channel.name,
                'category': category,
                'message_id': str(message_id)
            })

        return web.json_response({'bars': bars_data, 'count': len(bars_data)})

    async def handle_global_update(self, request):
        """Updates the text content of ALL bars (Master Bar propagation)."""
        try:
            data = await request.json()
            new_content = data.get('content')
            
            if not new_content:
                return web.json_response({'error': 'Missing content'}, status=400)
                
            # Call the existing function in NyxOS.py
            # We need to access the method. Since 'bot' is just the client,
            # we might need to invoke the logic directly or via a helper.
            # Ideally, NyxOS.py methods should be accessible.
            # But global_update_bars is a standalone async function in NyxOS.py context?
            # Or a method of the Client? 
            
            # Assuming NyxOS.py structure: the functions are likely standalone or attached to client.
            # Based on codebase_investigator, they are standalone functions that take 'client' as arg
            # OR they are methods if the bot is a class.
            
            # Codebase check showed they are likely methods of LMStudioBot or standalone.
            # I will assume they are attached to the bot instance or I need to import them.
            # Let's double check this integration point in the next step.
            
            if hasattr(self.bot, 'global_update_bars'):
                 await self.bot.global_update_bars(new_content)
                 return web.json_response({'status': 'success', 'updated_content': new_content})
            else:
                 return web.json_response({'error': 'Bot function not found'}, status=500)

        except Exception as e:
            logger.error(f"API Error: {e}")
            return web.json_response({'error': str(e)}, status=500)

    async def handle_global_state(self, request):
        """Sleep/Idle/Awake all bars."""
        try:
            data = await request.json()
            action = data.get('action') # 'sleep', 'idle', 'awake'
            
            if action == 'sleep':
                if hasattr(self.bot, 'sleep_all_bars'):
                    await self.bot.sleep_all_bars(None) # Interaction is None
            elif action == 'idle':
                if hasattr(self.bot, 'idle_all_bars'):
                    await self.bot.idle_all_bars(None)
            elif action == 'awake':
                 if hasattr(self.bot, 'awake_all_bars'):
                    await self.bot.awake_all_bars(None)
            else:
                return web.json_response({'error': 'Invalid action'}, status=400)
                
            return web.json_response({'status': 'success', 'action': action})
        except Exception as e:
            logger.error(f"API Error: {e}")
            return web.json_response({'error': str(e)}, status=500)

    async def handle_bar_update(self, request):
        """Updates a specific bar."""
        # To be implemented for granular control
        return web.json_response({'status': 'not_implemented_yet'})
