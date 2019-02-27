from meowth import Cog, command, bot, checks
from meowth.utils.converters import ChannelMessage
from meowth.exts.pkmn import Pokemon, Move
from meowth.exts.want import Want
from meowth.exts.users import MeowthUser
from meowth.utils import formatters

from discord.ext import commands

import asyncio
from functools import partial

class Trade():

    def __init__(self, bot, guild_id, lister_id, listing_id, offered_pkmn, wanted_pkmn, offer_list = []):
        self.bot = bot
        self.guild_id = guild_id
        self.lister_id = lister_id
        self.listing_id = listing_id
        self.offered_pkmn = offered_pkmn
        self.wanted_pkmn = wanted_pkmn
        self.offer_list = offer_list
    
    @property
    def lister_name(self):
        g = self.bot.get_guild(self.guild_id)
        m = g.get_member(self.lister_id)
        return m.display_name
    
    @property
    def lister(self):
        g = self.bot.get_guild(self.guild_id)
        m = g.get_member(self.lister_id)
        return m
    
    @property
    def lister_avy(self):
        u = self.bot.get_user(self.lister_id)
        return u.avatar_url
    
    @property
    def react_list(self):
        return formatters.mc_emoji(len(self.wanted_pkmn))
    
    @property
    def offer_msgs(self):
        return [x['msg'] for x in self.offer_list]

    async def listing_chnmsg(self):
        chn, msg = await ChannelMessage.from_id_string(self.bot, self.listing_id)
        return chn, msg
    
    @staticmethod
    async def make_offer_embed(trader, listed_pokemon, offer):
        return formatters.make_embed(
            title="Pokemon Trade Offer",
            # icon=Trade.icon_url,
            fields={
                "You Offered": await listed_pokemon.trade_display_str(),
                "They Offer": await offer.trade_display_str()
                },
            inline=True,
            footer=trader.display_name,
            footer_icon=trader.avatar_url_as(format='png', size=256),
            thumbnail=await offer.sprite_url()
        )
    
    async def make_offer(self, trader, listed_pokemon, offered_pokemon):
        offer_dict = {
            'trader': trader.id,
            'listed': listed_pokemon,
            'offered': offered_pokemon,
        }
        embed = await self.make_offer_embed(trader, listed_pokemon, offered_pokemon)
        offermsg = await trader.send(
            f"{trader.display_name} has made an offer on your trade! Use the reactions to accept or reject the offer.",
            embed=embed
        )
        react_list = ['✅', '❎']
        for react in react_list:
            await offermsg.add_reaction(react)
        offer_dict['msg'] = f'{offermsg.channel.id}/{offermsg.id}'
        self.offer_list.append(offer_dict)
        offer_list_data = [repr(x) for x in self.offer_list]
        trade_table = self.bot.dbi.table('trades')
        update = trade_table.update.where(id=self.id)
        update.values(offer_list=offer_list_data)
        await update.commit()
    
    async def accept_offer(self, trader, listed, offer):
        content = f'{self.lister_name} has accepted your trade offer! Please DM them to coordinate the trade.'
        embed = await self.make_offer_embed(self.lister, offer, listed)
        await trader.send(content, embed=embed)
        trade_table = self.bot.dbi.table('trades')
        query = trade_table.query.where(id=self.id)
        chn, msg = await self.listing_chnmsg()
        await msg.delete()
        return await query.delete()    

    async def on_raw_reaction_add(self, payload):
        idstring = f'{payload.channel_id}/{payload.message_id}'
        if idstring != self.listing_id and idstring not in self.offer_msgs:
            return
        if payload.emoji.is_custom_emoji():
            emoji = payload.emoji.id
        else:
            emoji = str(payload.emoji)
        if idstring == self.listing_id:
            if emoji not in self.react_list:
                return
            i = self.react_list.index(emoji)
            offer = self.wanted_pkmn[i]
            g = self.bot.get_guild(self.guild_id)
            trader = g.get_member(payload.user_id)
            if len(self.offered_pkmn) > 1:
                content = f"{trader.display_name}, which of the following Pokemon do you want to trade for?"
                mc_emoji = formatters.mc_emoji(len(self.offered_pkmn))
                choice_dict = dict(zip(mc_emoji, self.offered_pkmn))
                display_list = [await x.trade_display_str() for x in self.offered_pkmn]
                display_dict = dict(zip(mc_emoji, display_list))
                embed = formatters.mc_embed(display_dict)
                channel = self.bot.get_channel(payload.channel_id)
                choicemsg = await channel.send(content, embed=embed)
                response = await formatters.ask(self.bot, [choicemsg], user_list=[trader.id],
                    react_list=mc_emoji)
                pkmn = choice_dict[str(response.emoji)]
            else:
                pkmn = self.offered_pkmn[0]
            return await self.make_offer(trader, pkmn, offer)
        if idstring in self.offer_msgs:
            if emoji == '\u2705':
                for offer in self.offer_list:
                    if offer['msg'] == idstring:
                        g = self.bot.get_guild(self.guild_id)
                        trader = g.get_member(offer['trader'])
                        listed = offer['listed']
                        offered = offer['offered']
                        return await self.accept_offer(trader, listed, offered)
            
        


class TradeCog(Cog):

    def __init__(self, bot):
        self.bot = bot
    
    @command(aliases=['t'])
    async def trade(self, ctx, offers: commands.Greedy[Pokemon]):
        listmsg = await ctx.send(f"{ctx.author.display_name} - what Pokemon are you willing to accept in exchange? Use 'any' if you will accept anything and 'OBO' if you want to allow other offers. Use commas to separate Pokemon.")
        def check(m):
            return m.channel == ctx.channel and m.author == ctx.author
        wantmsg = await ctx.bot.wait_for('message', check=check)
        wantargs = wantmsg.content.lower().split(',')
        wantargs = list(map(str.strip, wantargs))
        if 'any' in wantargs:
            wantargs.remove('any')
            accept_any = True
        else:
            accept_any = False
        if 'obo' in wantargs:
            wantargs.remove('obo')
            accept_other = True
        else:
            accept_other = False
        pkmn_convert = partial(Pokemon.convert, ctx)
        wants = [await pkmn_convert(arg) for arg in wantargs]
        if accept_any:
            wants.append('any')
        if accept_other:
            wants.append('obo')
        listing_id = f'{ctx.channel.id}/{listmsg.id}'
        new_trade = Trade(self.bot, ctx.guild.id, ctx.author.id, listing_id, offers, wants)
        embed = await TradeEmbed.from_trade(new_trade)
        await wantmsg.delete()
        await listmsg.edit(content="", embed=embed.embed)
        want_emoji = formatters.mc_emoji(len(wants))
        for emoji in want_emoji:
            await listmsg.add_reaction(emoji)
        offer_data = [repr(x) for x in offers]
        want_data = [repr(x) for x in wants]
        data = {
            'guild_id': ctx.guild.id,
            'lister_id': ctx.author.id,
            'listing_id': listing_id,
            'offers': offer_data,
            'wants': want_data,
        }
        trade_table = ctx.bot.dbi.table('trades')
        insert = trade_table.insert.row(**data)
        insert.returning('id')
        rcrd = await insert.commit()
        new_trade.id = rcrd[0][0]
        ctx.bot.add_listener(new_trade.on_raw_reaction_add)




    
class TradeEmbed():
    
    def __init__(self, embed):
        self.embed = embed
    
    want_index = 0
    offer_index = 1

    @classmethod
    async def from_trade(cls, trade):
        want_list = []
        want_emoji = formatters.mc_emoji(len(trade.wanted_pkmn))
        for i in range(len(trade.wanted_pkmn)):
            if isinstance(trade.wanted_pkmn[i], Pokemon):
                want_str = f'{want_emoji[i]}: {await trade.wanted_pkmn[i].trade_display_str()}'
            elif trade.wanted_pkmn[i] == 'any':
                want_str = f'{want_emoji[i]}: Any Pokemon'
            elif trade.wanted_pkmn[i] == 'obo':
                want_str = f'{want_emoji[i]}: Other Pokemon'
            want_list.append(want_str)
        offer_list = []
        for i in range(len(trade.offered_pkmn)):
            offer_str = await trade.offered_pkmn[i].trade_display_str()
            offer_list.append(offer_str)
        title = "Pokemon Trade"
        footer = trade.lister_name
        footer_url = trade.lister_avy
        fields = {'Wants': "\n".join(want_list), 'Offers': "\n".join(offer_list)}
        if len(offer_list) == 1:
            thumbnail = await trade.offered_pkmn[0].sprite_url()
        else:
            thumbnail = None
        embed = formatters.make_embed(title=title, footer=footer, footer_icon=footer_url,
            fields=fields, thumbnail=thumbnail)
        return cls(embed)

        
