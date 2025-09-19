import telebot
from telebot import types
import logging
import chess
import random
import time
import sqlite3
import uuid
import json

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

bot = telebot.TeleBot("YOUR_TOKEN")

def init_db():
    conn = sqlite3.connect('chess_games.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS games (
        game_id TEXT PRIMARY KEY,
        chat_id INTEGER,
        mode TEXT,
        players TEXT,
        board_fen TEXT,
        current_turn INTEGER,
        selected TEXT,
        message_id INTEGER,
        last_update REAL
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS leaderboard (
        user_id INTEGER,
        username TEXT,
        points INTEGER DEFAULT 0,
        PRIMARY KEY (user_id)
    )''')
    conn.commit()
    conn.close()

init_db()


waiting_players = {}  # {game_id: {'host': player1, 'mode': 'pvp' or 'bot', 'chat_id': chat_id, 'host_id': user_id}}
active_games = {}    # {game_id: {'mode': 'pvp' or 'bot', 'players': [p1, p2 or 'bot'], 'player_ids': [id1, id2 or None], 'board': chess.Board(), 'current': chess.WHITE, 'selected': None, 'message_id': None, 'last_update': 0, 'chat_id': chat_id}}


MOVE_DOT = '🔵'
CAPTURE_DOT = '🔴'
SQUARE_LIGHT = ' '  
SQUARE_DARK = ' '   

PIECE_TO_EMOJI = {
    'P': '♙', 'R': '♖', 'N': '♘', 'B': '♗', 'Q': '♕', 'K': '♔',
    'p': '♟️', 'r': '♜', 'n': '♞', 'b': '♝', 'q': '♛', 'k': '♚'
}

def piece_to_emoji(piece, row, col):
    if piece is None:
        return SQUARE_LIGHT if (row + col) % 2 == 0 else SQUARE_DARK
    return PIECE_TO_EMOJI.get(piece.symbol(), ' ')

def save_game(game_id):
    game = active_games[game_id]
    conn = sqlite3.connect('chess_games.db')
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO games (game_id, chat_id, mode, players, board_fen, current_turn, selected, message_id, last_update)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                 (game_id, game['chat_id'], game['mode'], json.dumps(game['players']), game['board'].fen(),
                  game['current'], json.dumps(game.get('selected')), game['message_id'], game['last_update']))
    conn.commit()
    conn.close()

def load_games():
    conn = sqlite3.connect('chess_games.db')
    c = conn.cursor()
    c.execute('SELECT * FROM games')
    for row in c.fetchall():
        game_id, chat_id, mode, players, board_fen, current_turn, selected, message_id, last_update = row
        active_games[game_id] = {
            'chat_id': chat_id,
            'mode': mode,
            'players': json.loads(players),
            'player_ids': [None, None] if mode == 'bot' else json.loads(players),  
            'board': chess.Board(board_fen),
            'current': bool(current_turn),
            'selected': json.loads(selected) if selected else None,
            'message_id': message_id,
            'last_update': last_update
        }
    conn.close()

def update_leaderboard(winner=None, loser=None, is_draw=False, players=None, mode='pvp'):
    if mode != 'pvp':
        return  
    conn = sqlite3.connect('chess_games.db')
    c = conn.cursor()
    if is_draw and players:
        for player in players:
            c.execute('INSERT OR IGNORE INTO leaderboard (user_id, username, points) VALUES (?, ?, 0)', 
                      (player['id'], player['username']))
            c.execute('UPDATE leaderboard SET points = points + 1 WHERE user_id = ?', (player['id'],))
    elif winner and loser:
        c.execute('INSERT OR IGNORE INTO leaderboard (user_id, username, points) VALUES (?, ?, 0)', 
                  (winner['id'], winner['username']))
        c.execute('UPDATE leaderboard SET points = points + 3 WHERE user_id = ?', (winner['id'],))
        c.execute('INSERT OR IGNORE INTO leaderboard (user_id, username, points) VALUES (?, ?, 0)', 
                  (loser['id'], loser['username']))
    conn.commit()
    conn.close()


def check_subscription(user_id):
    try:
        member = bot.get_chat_member('@SYR_SB', user_id)
        return member.status in ['member', 'administrator', 'creator']
    except:
        return False

@bot.message_handler(func=lambda message: message.text.lower() == "توب الشطرنج")
def show_leaderboard(message):
    if not check_subscription(message.from_user.id):
        bot.reply_to(message, "⚠️ يرجى الاشتراك في @SYR_SB أولاً!")
        return
    
    conn = sqlite3.connect('chess_games.db')
    c = conn.cursor()
    c.execute('SELECT username, points FROM leaderboard ORDER BY points DESC LIMIT 5')
    leaders = c.fetchall()
    conn.close()
    
    if not leaders:
        bot.reply_to(message, "🏆 قائمة الشطرنج فارغة!")
        return
    
    text = "🏆 توب الشطرنج (أفضل 5 لاعبين):\n"
    for i, (username, points) in enumerate(leaders, 1):
        text += f"{i}. {username}: {points} نقاط\n"
    bot.reply_to(message, text)

@bot.message_handler(func=lambda message: message.text.lower() == "نقاطي الشطرنج")
def my_chess_points(message):
    user_id = message.from_user.id
    user = message.from_user.username or message.from_user.first_name
    
    if not check_subscription(user_id):
        bot.reply_to(message, "⚠️ يرجى الاشتراك في @SYR_SB أولاً!")
        return
    
    conn = sqlite3.connect('chess_games.db')
    c = conn.cursor()
    c.execute('SELECT points FROM leaderboard WHERE user_id = ?', (user_id,))
    result = c.fetchone()
    conn.close()
    
    if result is None:
        bot.reply_to(message, f"@{user} ليس لديك نقاط بعد! العب مباريات PVP لتجميع النقاط.")
        return
    
    points = result[0]
    bot.reply_to(message, f"@{user} نقاطك في الشطرنج: {points} نقاط")

@bot.message_handler(commands=['start', 'chess'])
def start_chess(message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    user = message.from_user.username or message.from_user.first_name
    
    if not check_subscription(user_id):
        markup = types.InlineKeyboardMarkup()
        btn_sub = types.InlineKeyboardButton("🔔 اشترك في القناة", url='https://t.me/SYR_SB')
        btn_check = types.InlineKeyboardButton("✅ تحقق من الاشتراك", callback_data=f"check_sub_{chat_id}_{user_id}")
        markup.add(btn_sub, btn_check)
        bot.reply_to(message, "⚠️ يرجى الاشتراك في قناتنا @SYR_SB لاستخدام البوت!", reply_markup=markup)
        return
    
    
    welcome_message = (
        "♟️ مرحبا بك في بوت الشطرنج! من خلالي يمكنك اللعب ضد أصدقائك في المجموعة. الشطرنج بشكل كامل وجميل!\n\n"
        "🔥 **مميزات البوت**:\n"
        "- 🎮 اكتب تحدي شطرنج لبدء تحدي مع لاعب آخر.\n"
        "- 🏆 اكتب توب الشطرنج لعرض قائمة أفضل 5 لاعبين.\n"
        "- 📊 اكتب نقاطي الشطرنج لعرض نقاطك الشخصية.\n"
        "- 🤖 جرب اللعب ضد البوت للتدريب.\n"
        "- 📝 ملاحظة: اللعب ضد البوت مستوى سهل جدًا وتجريبي للبوت فقط.\n\n"
        "اختر أدناه أو ابدأ اللعب:"
    )
    
    markup = types.InlineKeyboardMarkup()
    btn_add_to_group = types.InlineKeyboardButton("➕ أضفني إلى مجموعتك", url="https://t.me/S963_bot?startgroup=true")
    btn_bot = types.InlineKeyboardButton("🤖 لعب ضد البوت", callback_data=f"mode_bot_{chat_id}")
    markup.add(btn_add_to_group, btn_bot)
    bot.send_message(chat_id, welcome_message, reply_markup=markup)

@bot.message_handler(func=lambda message: message.text.lower() == "تحدي شطرنج")
def chess_challenge(message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    user = message.from_user.username or message.from_user.first_name
    
    if not check_subscription(user_id):
        bot.reply_to(message, "⚠️ يرجى الاشتراك في @SYR_SB أولاً!")
        return
    
    game_id = str(uuid.uuid4())
    waiting_players[game_id] = {'host': user, 'host_id': user_id, 'mode': 'pvp', 'chat_id': chat_id}
    markup = types.InlineKeyboardMarkup()
    btn_join = types.InlineKeyboardButton("🎮 قبول التحدي!", callback_data=f"join_{game_id}")
    markup.add(btn_join)
    bot.send_message(chat_id, f"⚔ {user} يرغب بتحدي في لعبة شطرنج! هل من منافس؟", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('check_sub_'))
def check_sub_callback(call):
    data = call.data.split('_')
    chat_id = int(data[2])
    user_id = int(data[3])
    
    if check_subscription(user_id):
        bot.answer_callback_query(call.id, "✔️ تم التحقق!")
        bot.delete_message(chat_id, call.message.message_id)
        markup = types.InlineKeyboardMarkup()
        btn_add_to_group = types.InlineKeyboardButton("➕ أضفني إلى مجموعتك", url="https://t.me/S963_bot?startgroup=true")
        btn_bot = types.InlineKeyboardButton("🤖 لعب ضد البوت", callback_data=f"mode_bot_{chat_id}")
        markup.add(btn_add_to_group, btn_bot)
        bot.send_message(chat_id, "تم التحقق اضغط /start", reply_markup=markup)
    else:
        bot.answer_callback_query(call.id, "❌ لم تشترك بعد!", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data.startswith('mode_'))
def choose_mode(call):
    data = call.data.split('_')
    mode = data[1]
    chat_id = int(data[2])
    user_id = call.from_user.id
    user = call.from_user.username or call.from_user.first_name
    
    if not check_subscription(user_id):
        bot.answer_callback_query(call.id, "⚠️ يرجى الاشتراك في @SYR_SB أولاً!", show_alert=True)
        return
    
    game_id = str(uuid.uuid4())
    if mode == 'pvp':
        waiting_players[game_id] = {'host': user, 'host_id': user_id, 'mode': 'pvp', 'chat_id': chat_id}
        show_join_button(game_id, user, chat_id)
    elif mode == 'bot':
        active_games[game_id] = {
            'chat_id': chat_id,
            'mode': 'bot',
            'players': [user, 'bot'],
            'player_ids': [user_id, None],
            'board': chess.Board(),
            'current': chess.WHITE,
            'selected': None,
            'message_id': None,
            'last_update': 0
        }
        msg = send_chess_board(game_id, call)
        active_games[game_id]['message_id'] = msg.message_id
        save_game(game_id)
        bot.delete_message(chat_id, call.message.message_id)
    
    bot.answer_callback_query(call.id, f"✔ تم اختيار وضع {mode.upper()}")

def show_join_button(game_id, host, chat_id):
    markup = types.InlineKeyboardMarkup()
    btn_join = types.InlineKeyboardButton("🎮 انضم للعبة!", callback_data=f"join_{game_id}")
    markup.add(btn_join)
    bot.send_message(chat_id, f"⚔ {host} يبحث عن خصم في وضع PVP!", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('join_'))
def join_game(call):
    game_id = call.data.split('_')[1]
    user_id = call.from_user.id
    challenger = call.from_user.username or call.from_user.first_name
    
    if not check_subscription(user_id):
        bot.answer_callback_query(call.id, "⚠️ يرجى الاشتراك في @SYR_SB أولاً!", show_alert=True)
        return
    
    if game_id not in waiting_players:
        bot.answer_callback_query(call.id, "❌ اللعبة لم تعد متاحة!", show_alert=True)
        return
        
    if challenger == waiting_players[game_id]['host']:
        bot.answer_callback_query(call.id, "❌ لا يمكنك لعب نفسك!", show_alert=True)
        return
        
    chat_id = waiting_players[game_id]['chat_id']
    active_games[game_id] = {
        'chat_id': chat_id,
        'mode': 'pvp',
        'players': [waiting_players[game_id]['host'], challenger],
        'player_ids': [waiting_players[game_id]['host_id'], user_id],
        'board': chess.Board(),
        'current': chess.WHITE,
        'selected': None,
        'message_id': None,
        'last_update': 0
    }
    del waiting_players[game_id]
    bot.delete_message(chat_id, call.message.message_id)
    msg = send_chess_board(game_id, call)
    active_games[game_id]['message_id'] = msg.message_id
    save_game(game_id)

def send_chess_board(game_id, call=None):
    game = active_games[game_id]
    chat_id = game['chat_id']
    board = game['board']
    selected = game.get('selected')
    markup = types.InlineKeyboardMarkup(row_width=8)
    
    possible_moves = []
    if selected:
        square = chess.square(selected[1], 7 - selected[0])
        for move in board.legal_moves:
            if move.from_square == square:
                possible_moves.append(move.to_square)
    
    for row in range(7, -1, -1):
        row_buttons = []
        for col in range(8):
            square = chess.square(col, row)
            piece = board.piece_at(square)
            text = piece_to_emoji(piece, row, col)
            
            if selected and square in possible_moves:
                if piece and piece.color != game['current']:
                    text = CAPTURE_DOT + text
                else:
                    text = MOVE_DOT + text
            
            callback = f"move_{game_id}_{7-row}_{col}"
            row_buttons.append(types.InlineKeyboardButton(text, callback_data=callback))
        markup.add(*row_buttons)
    
    if game['mode'] == 'pvp':
        p1, p2 = game['players']
    else:
        p1, p2 = game['players'][0], 'البوت'
    
    current_player = p1 if game['current'] == chess.WHITE else p2
    status = f"🎮 اللاعبون:\nالأبيض: {p1}\nالأسود: {p2}\n\nالدور لـ: {current_player}\n\n"
    
    if board.is_check():
        status += "🚨 كش!"
    if board.is_checkmate():
        if game['mode'] == 'pvp':
            winner = {'id': game['player_ids'][1] if game['current'] == chess.WHITE else game['player_ids'][0], 
                      'username': p2 if game['current'] == chess.WHITE else p1}
            loser = {'id': game['player_ids'][0] if game['current'] == chess.WHITE else game['player_ids'][1], 
                     'username': p1 if game['current'] == chess.WHITE else p2}
            update_leaderboard(winner, loser, mode=game['mode'])
        status += f"🏆 كش مات! الفائز: {p2 if game['current'] == chess.WHITE else p1}"
        del active_games[game_id]
        conn = sqlite3.connect('chess_games.db')
        c = conn.cursor()
        c.execute('DELETE FROM games WHERE game_id = ?', (game_id,))
        conn.commit()
        conn.close()
    elif board.is_stalemate():
        status += "🤝 تعادل!"
        if game['mode'] == 'pvp':
            players = [
                {'id': game['player_ids'][0], 'username': game['players'][0]},
                {'id': game['player_ids'][1], 'username': game['players'][1]}
            ]
            update_leaderboard(is_draw=True, players=players, mode=game['mode'])
        del active_games[game_id]
        conn = sqlite3.connect('chess_games.db')
        c = conn.cursor()
        c.execute('DELETE FROM games WHERE game_id = ?', (game_id,))
        conn.commit()
        conn.close()
    
    return bot.send_message(chat_id, status, reply_markup=markup)

def update_chess_board(game_id, call=None):
    game = active_games[game_id]
    chat_id = game['chat_id']
    board = game['board']
    message_id = game['message_id']
    selected = game.get('selected')
    markup = types.InlineKeyboardMarkup(row_width=8)
    
    possible_moves = []
    if selected:
        square = chess.square(selected[1], 7 - selected[0])
        for move in board.legal_moves:
            if move.from_square == square:
                possible_moves.append(move.to_square)
    
    for row in range(7, -1, -1):
        row_buttons = []
        for col in range(8):
            square = chess.square(col, row)
            piece = board.piece_at(square)
            text = piece_to_emoji(piece, row, col)
            
            if selected and square in possible_moves:
                if piece and piece.color != game['current']:
                    text = CAPTURE_DOT + text
                else:
                    text = MOVE_DOT + text
            
            callback = f"move_{game_id}_{7-row}_{col}"
            row_buttons.append(types.InlineKeyboardButton(text, callback_data=callback))
        markup.add(*row_buttons)
    
    if game['mode'] == 'pvp':
        p1, p2 = game['players']
    else:
        p1, p2 = game['players'][0], 'البوت'
    
    current_player = p1 if game['current'] == chess.WHITE else p2
    status = f"🎮 اللاعبون:\nالأبيض: {p1}\nالأسود: {p2}\n\nالدور لـ: {current_player}\n\n"
    
    if board.is_check():
        status += "🚨 كش!"
    if board.is_checkmate():
        if game['mode'] == 'pvp':
            winner = {'id': game['player_ids'][1] if game['current'] == chess.WHITE else game['player_ids'][0], 
                      'username': p2 if game['current'] == chess.WHITE else p1}
            loser = {'id': game['player_ids'][0] if game['current'] == chess.WHITE else game['player_ids'][1], 
                     'username': p1 if game['current'] == chess.WHITE else p2}
            update_leaderboard(winner, loser, mode=game['mode'])
        status += f"🏆 كش مات! الفائز: {p2 if game['current'] == chess.WHITE else p1}"
        del active_games[game_id]
        conn = sqlite3.connect('chess_games.db')
        c = conn.cursor()
        c.execute('DELETE FROM games WHERE game_id = ?', (game_id,))
        conn.commit()
        conn.close()
        return
    elif board.is_stalemate():
        status += "🤝 تعادل!"
        if game['mode'] == 'pvp':
            players = [
                {'id': game['player_ids'][0], 'username': game['players'][0]},
                {'id': game['player_ids'][1], 'username': game['players'][1]}
            ]
            update_leaderboard(is_draw=True, players=players, mode=game['mode'])
        del active_games[game_id]
        conn = sqlite3.connect('chess_games.db')
        c = conn.cursor()
        c.execute('DELETE FROM games WHERE game_id = ?', (game_id,))
        conn.commit()
        conn.close()
        return
    
    current_time = time.time()
    if current_time - game['last_update'] < 0.5:
        time.sleep(0.5 - (current_time - game['last_update']))
    game['last_update'] = time.time()
    
    try:
        bot.edit_message_text(status, chat_id, message_id, reply_markup=markup)
    except telebot.apihelper.ApiTelegramException as e:
        if e.error_code == 400 and 'not modified' in e.description.lower():
            pass
        else:
            raise
    save_game(game_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('move_'))
def handle_move(call):
    data = call.data.split('_')
    game_id = data[1]
    row = int(data[2])
    col = int(data[3])
    user_id = call.from_user.id
    user = call.from_user.username or call.from_user.first_name

    if game_id not in active_games:
        bot.answer_callback_query(call.id, "❌ اللعبة انتهت!", show_alert=True)
        return

    if not check_subscription(user_id):
        bot.answer_callback_query(call.id, "⚠️ يرجى الاشتراك في @SYR_SB أولاً!", show_alert=True)
        return

    game = active_games[game_id]
    board = game['board']

    if game['mode'] == 'pvp':
        player_index = 0 if user == game['players'][0] else 1 if user == game['players'][1] else -1
        if player_index == -1:
            bot.answer_callback_query(call.id, "❌ هذه اللعبة ليست لك!", show_alert=True)
            return
        expected = 0 if game['current'] == chess.WHITE else 1
        if player_index != expected:
            bot.answer_callback_query(call.id, "⏳ ليس دورك الآن!", show_alert=True)
            return
    elif game['mode'] == 'bot' and game['current'] == chess.BLACK:
        bot.answer_callback_query(call.id, "🤖 دور البوت الآن!", show_alert=True)
        return
    elif game['mode'] == 'bot' and user != game['players'][0]:
        bot.answer_callback_query(call.id, "❌ هذه اللعبة ليست لك!", show_alert=True)
        return

    selected = game.get('selected')
    square = chess.square(col, 7 - row)

    if not selected:
        piece = board.piece_at(square)
        if not piece or piece.color != game['current']:
            bot.answer_callback_query(call.id, "❌ اختر قطعة تابعة لك!", show_alert=True)
            return
        game['selected'] = (row, col)
        bot.answer_callback_query(call.id, f"✔ اخترت القطعة في {chess.square_name(square)}")
        update_chess_board(game_id, call)
        return

    from_square = chess.square(selected[1], 7 - selected[0])
    to_square = square
    move = chess.Move(from_square, to_square)

    if board.piece_at(from_square).piece_type == chess.PAWN and (chess.square_rank(to_square) == 7 or chess.square_rank(to_square) == 0):
        move.promotion = chess.QUEEN

    if move in board.legal_moves:
        board.push(move)
        game.pop('selected', None)
        game['current'] = not game['current']
        
        if board.is_game_over():
            update_chess_board(game_id, call)
            return
        
        if game['mode'] == 'bot' and game['current'] == chess.BLACK:
            legal_moves = list(board.legal_moves)
            bot_move = random.choice(legal_moves)
            board.push(bot_move)
            game['current'] = chess.WHITE
        
        update_chess_board(game_id, call)
    else:
        bot.answer_callback_query(call.id, "❌ حركة غير صالحة!", show_alert=True)
        game.pop('selected', None)
        update_chess_board(game_id, call)

@bot.message_handler(commands=['help'])
def help_command(message):
    if not check_subscription(message.from_user.id):
        bot.reply_to(message, "⚠️ يرجى الاشتراك في @SYR_SB أولاً!")
        return
    help_text = """
🛡️ مرحبا بك في بوت الشطرنج المتكامل!
**الأوامر والتعليمات:**
- /chess: بدء لعبة جديدة
- اكتب "تحدي شطرنج" لتحدي لاعب في المجموعة
- اكتب "توب الشطرنج" لعرض أفضل 5 لاعبين بناءً على النقاط
- اكتب "نقاطي الشطرنج" لعرض نقاطك الشخصية
- /help: عرض هذا الدليل

**نظام النقاط (في وضع لاعب ضد لاعب فقط):**
- الفوز: 3 نقاط
- التعادل: 1 نقطة
- الخسارة: 0 نقاط
- ملاحظة: اللعب ضد البوت لا يمنح نقاط.

**كيف تلعب:**
- اختر وضع PVP أو PVE.
- في PVP، انتظر خصمًا. في PVE، واجه البوت.
- الهدف: حاصر ملك الخصم (كش مات).
- استخدم الأزرار لتحريك القطع.

**لماذا الشطرنج؟**
- تحسن التركيز والاستراتيجية.
- منافسة ممتعة مع أصدقائك!

استمتع! ♟️
"""
    bot.reply_to(message, help_text)


load_games()
bot.polling()