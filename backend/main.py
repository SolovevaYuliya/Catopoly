from fastapi import FastAPI, Request, Depends, HTTPException, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path
from datetime import datetime, timezone
import shutil
import os
import random
from typing import Optional

from backend import models
from backend.database import engine, SessionLocal

# --- ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ---
models.Base.metadata.create_all(bind=engine)

app = FastAPI()

# --- НАСТРОЙКА ПУТЕЙ ---
BASE_DIR = Path(__file__).resolve().parent.parent
FRONTED_DIR = BASE_DIR / "fronted"
UPLOAD_DIR = BASE_DIR / "uploads"

# Создаем папки для загрузки, если их нет
os.makedirs(UPLOAD_DIR / "avatars", exist_ok=True)

# Монтируем статику (стили, скрипты) и загрузки (аватарки)
app.mount("/static", StaticFiles(directory=str(FRONTED_DIR)), name="static")
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

# Настраиваем шаблонизатор Jinja2
templates = Jinja2Templates(directory=str(FRONTED_DIR))


# --- ЗАВИСИМОСТИ И ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def get_db():
    """Открытие и закрытие сессии базы данных"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def get_current_user(request: Request, db: Session = Depends(get_db)):
    """Получает текущего пользователя из куки 'user_id'"""
    user_id = request.cookies.get("user_id")
    if not user_id:
        return None
    try:
        return db.query(models.users).filter(models.users.id == int(user_id)).first()
    except:
        return None


def get_base_context(request: Request, user: models.users, db: Session):
    """Формирует базовый набор данных для каждой страницы (например, инвайты)"""
    invites = []
    if user:
        # Тянем инвайты и имена тех, кто их прислал
        invites = db.query(models.invitations, models.users.username).join(
            models.users, models.invitations.sender_id == models.users.id
        ).filter(
            models.invitations.recipient_id == user.id,
            models.invitations.status == "pending"
        ).all()

    return {
        "request": request,
        "user": user,
        "pending_invites": invites
    }


# --- МАРШРУТЫ АВТОРИЗАЦИИ ---


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html")


@app.post("/login")
async def login_user(
    request: Request,                  # <--- ОБЯЗАТЕЛЬНО: добавили прием запроса
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    # Ищем пользователя в базе
    user = db.query(models.users).filter(
        models.users.email == email,
        models.users.password_hash == password
    ).first()

    # Если не нашли — возвращаем страницу логина с ошибкой
    if not user:
        return templates.TemplateResponse(
            request=request,            # <--- Передаем объект запроса первым
            name="login.html",          # <--- Явно пишем имя файла
            context={                   # <--- Данные для шаблона теперь в блоке context
                "error": "Неверный логин или пароль"
            }
        )

    # Если всё ок — логиним и кидаем на главную
    res = RedirectResponse("/", status_code=303)
    res.set_cookie(key="user_id", value=str(user.id))
    return res


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse(request=request, name="register.html")


@app.post("/register")
async def register_user(
        request: Request,  # <--- 1. Добавили прием запроса
        username: str = Form(...),
        email: str = Form(...),
        password: str = Form(...),
        db: Session = Depends(get_db)
):
    # Проверка на дубликат email
    existing = db.query(models.users).filter(models.users.email == email).first()

    if existing:
        # 2. Переписали возврат шаблона по новому стандарту
        return templates.TemplateResponse(
            request=request,  # <--- Передаем настоящий запрос
            name="register.html",
            context={  # <--- Данные для Jinja2 теперь здесь
                "error": "Этот Email уже занят"
            }
        )

    # Создаем нового котика
    new_user = models.users(
        username=username,
        email=email,
        password_hash=password,
        created_at=datetime.now(timezone.utc)
    )
    db.add(new_user)
    db.commit()

    return RedirectResponse("/login", status_code=303)


@app.get("/logout")
async def logout():
    res = RedirectResponse("/login", status_code=303)
    res.delete_cookie("user_id")
    return res


# --- ГЛАВНАЯ СТРАНИЦА ---

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request, db: Session = Depends(get_db), user: models.users = Depends(get_current_user)):
    if not user:
        return RedirectResponse("/login")

    ctx = get_base_context(request, user, db)
    ctx["current_page"] = "/"
    return templates.TemplateResponse(request=request, name="index.html", context=ctx)


# --- ЛОГИКА ПОИСКА И ЛОББИ ---

@app.get("/api/search", response_class=HTMLResponse)
async def read_search(request: Request, db: Session = Depends(get_db), user: models.users = Depends(get_current_user)):
    if not user:
        return RedirectResponse("/login")

    # 1. Находим ID игр, в которых этот юзер уже состоит
    user_joined_games = db.query(models.game_player.game_id).filter(models.game_player.user_id == user.id).all()
    joined_ids = [g[0] for g in user_joined_games]

    # 2. Фильтруем игры
    active_games = db.query(models.games).filter(
        models.games.status == "waiting",
        (models.games.is_private == False) |
        (models.games.owner_id == user.id) |
        (models.games.id.in_(joined_ids))
    ).all()

    lobbies = []
    for g in active_games:
        p_data = db.query(models.users).join(models.game_player, models.users.id == models.game_player.user_id).filter(models.game_player.game_id == g.id).all()
        lobbies.append({
            "id": g.id,
            "players": p_data,
            "max_players": g.max_players,
            "owner_id": g.owner_id,
            "is_private": g.is_private
        })

    f1 = [f[0] for f in db.query(models.friendships.friend_id).filter(models.friendships.user_id == user.id,
                                                                      models.friendships.status == "accepted").all()]
    f2 = [f[0] for f in db.query(models.friendships.user_id).filter(models.friendships.friend_id == user.id,
                                                                    models.friendships.status == "accepted").all()]
    actual_friends = db.query(models.users).filter(models.users.id.in_(f1 + f2)).all() if (f1 or f2) else []

    my_lobby = db.query(models.games).filter(models.games.owner_id == user.id, models.games.status == "waiting").first()

    ctx = get_base_context(request, user, db)
    ctx.update({
        "current_page": "/api/search",
        "lobbies": lobbies,
        "friends": actual_friends,
        "has_my_lobby": my_lobby is not None
    })
    return templates.TemplateResponse(request=request, name="search.html", context=ctx)


@app.post("/create_lobby")
async def create_lobby(
        max_players: int = Form(5),
        is_private: Optional[str] = Form(None),
        db: Session = Depends(get_db),
        user: models.users = Depends(get_current_user)
):
    if not user: return RedirectResponse("/login")

    existing = db.query(models.games).filter(models.games.owner_id == user.id, models.games.status == "waiting").first()
    if existing:
        return RedirectResponse(url="/api/search?error=limit")

    p_bool = True if is_private == "true" else False

    new_game = models.games(
        status="waiting",
        max_players=max_players,
        is_private=p_bool,
        owner_id=user.id,
        created_at=datetime.now(timezone.utc),
        current_player_turn=1,
        turn_number=1
    )
    db.add(new_game)
    db.commit()
    db.refresh(new_game)

    db.add(models.game_player(game_id=new_game.id, user_id=user.id, turn_order=1))
    db.commit()

    return RedirectResponse(url="/api/search", status_code=303)


@app.get("/join_lobby/{game_id}")
async def join_lobby(game_id: int, db: Session = Depends(get_db), user: models.users = Depends(get_current_user)):
    if not user: return RedirectResponse("/login")

    game = db.query(models.games).filter(models.games.id == game_id).first()
    count = db.query(models.game_player).filter(models.game_player.game_id == game_id).count()
    already = db.query(models.game_player).filter(models.game_player.game_id == game_id,
                                                  models.game_player.user_id == user.id).first()

    if game and not already and count < game.max_players:
        db.add(models.game_player(game_id=game_id, user_id=user.id, turn_order=count + 1))
        db.commit()

    return RedirectResponse(url="/api/search", status_code=303)


@app.get("/leave_lobby/{game_id}")
async def leave_lobby(game_id: int, db: Session = Depends(get_db), user: models.users = Depends(get_current_user)):
    if not user: return RedirectResponse("/login")
    db.query(models.game_player).filter(
        models.game_player.game_id == game_id,
        models.game_player.user_id == user.id
    ).delete()
    db.commit()
    return RedirectResponse(url="/api/search", status_code=303)


@app.get("/delete_lobby/{game_id}")
async def delete_lobby(game_id: int, db: Session = Depends(get_db), user: models.users = Depends(get_current_user)):
    game = db.query(models.games).filter(models.games.id == game_id, models.games.owner_id == user.id).first()
    if game:
        db.query(models.invitations).filter(models.invitations.game_id == game_id).delete()
        db.query(models.game_player).filter(models.game_player.game_id == game_id).delete()
        db.delete(game)
        db.commit()
    return RedirectResponse(url="/api/search", status_code=303)


# --- ЛОГИКА ИГРОВОГО ПРОЦЕССА ---

@app.get("/start_game/{game_id}")
async def start_game(game_id: int, db: Session = Depends(get_db), user: models.users = Depends(get_current_user)):
    game = db.query(models.games).filter(models.games.id == game_id, models.games.owner_id == user.id).first()
    if game:
        game.status = "playing"
        db.commit()
        return RedirectResponse(url=f"/game/{game_id}", status_code=303)
    return RedirectResponse(url="/api/search")


@app.get("/game/{game_id}", response_class=HTMLResponse)
async def view_game(game_id: int, request: Request, db: Session = Depends(get_db), user: models.users = Depends(get_current_user)):
    if not user: return RedirectResponse("/login")
    game = db.query(models.games).filter(models.games.id == game_id).first()
    if not game: return RedirectResponse("/api/search")

    p_data = db.query(models.users, models.game_player).filter(
        models.game_player.game_id == game_id,
        models.users.id == models.game_player.user_id
    ).order_by(models.game_player.turn_order).all()

    cells_data = db.query(models.cells).order_by(models.cells.id).all()

    # Печать в консоль PyCharm для отладки
    print(f"DEBUG: Viewing game {game_id}. Players: {len(p_data)}, Cells in DB: {len(cells_data)}")

    ctx = get_base_context(request, user, db)
    ctx.update({"game": game, "players_list": p_data, "cells": cells_data})
    return templates.TemplateResponse(request=request, name="game.html", context=ctx)


@app.post("/api/surrender/{game_id}")
async def surrender(game_id: int, db: Session = Depends(get_db), user: models.users = Depends(get_current_user)):
    if not user:
        return {"error": "Вы не авторизованы"}

    game = db.query(models.games).filter(models.games.id == game_id).first()
    player_entry = db.query(models.game_player).filter(
        models.game_player.game_id == game_id,
        models.game_player.user_id == user.id
    ).first()

    if player_entry:
        p_id = player_entry.id
        p_order = player_entry.turn_order

        # 1. Возвращаем поля банку
        db.query(models.property_ownership).filter(
            models.property_ownership.owner_id == p_id,
            models.property_ownership.game_id == game_id
        ).delete()

        # 2. Удаляем его сделки
        db.query(models.trades).filter(
            (models.trades.sender_id == p_id) | (models.trades.recipient_id == p_id)
        ).delete()

        # 3. ЛОГИКА ПЕРЕДАЧИ ХОДА (Самое важное!)
        if game.current_player_turn == p_order:
            # Ищем всех КРОМЕ того, кто сдается
            others = db.query(models.game_player).filter(
                models.game_player.game_id == game_id,
                models.game_player.id != p_id
            ).all()

            if others:
                # Берем список всех порядковых номеров ходов
                orders = [pl.turn_order for pl in others]
                # Пытаемся найти того, кто идет после нас
                next_potential = [o for o in orders if o > p_order]

                if next_potential:
                    game.current_player_turn = min(next_potential)
                else:
                    game.current_player_turn = min(orders)

                game.has_rolled = False
            else:
                # Если игроков больше нет — завершаем игру
                game.status = "finished"

        # 4. Лог
        new_log = models.game_log(
            game_id=game_id, player_id=p_id,
            action_text=f"собрал свои вещи и добровольно покинул коробку (сдался).",
            created_at=datetime.now(timezone.utc)
        )
        db.add(new_log)

        # 5. Удаляем игрока
        db.delete(player_entry)
        db.commit()

        return {"success": True}

    return {"error": "Вы не в игре"}

# --- ЛОГИКА ЧАТА ---

@app.post("/api/send_message/{game_id}")
async def send_message(game_id: int, text: str = Form(...), db: Session = Depends(get_db), user: models.users = Depends(get_current_user)):
    if not user or not text.strip(): return {"error": "empty"}
    db.add(models.game_chat(game_id=game_id, user_id=user.id, message=text.strip(), created_at=datetime.now(timezone.utc)))
    db.commit()
    return {"status": "ok"}


@app.post("/api/pay_jail/{game_id}")
async def pay_jail(game_id: int, db: Session = Depends(get_db), user: models.users = Depends(get_current_user)):
    game = db.query(models.games).filter(models.games.id == game_id).first()
    p = db.query(models.game_player).filter(models.game_player.game_id == game_id,
                                            models.game_player.user_id == user.id).first()

    if not p or game.current_player_turn != p.turn_order:
        return {"error": "Не твой ход!"}

    if not p.is_in_jail:
        return {"error": "Ты не в карантине"}

    if p.balance < 50:
        return {"error": "Недостаточно денег (нужно $50)"}

    # Списываем деньги и выпускаем
    p.balance -= 50
    p.is_in_jail = False
    p.jail_turns = 0

    db.add(models.game_log(game_id=game_id, player_id=p.id,
                           action_text="заплатил $50 и досрочно покинул карантин.",
                           created_at=datetime.now(timezone.utc)))
    db.commit()
    return {"success": True}

# --- ЛОГИКА ХОДА И ПОКУПКИ (С РЕНТОЙ) ---

@app.post("/api/roll_dice/{game_id}")
async def roll_dice(game_id: int, db: Session = Depends(get_db), user: models.users = Depends(get_current_user)):
    game = db.query(models.games).filter(models.games.id == game_id).first()
    p = db.query(models.game_player).filter(models.game_player.game_id == game_id,
                                            models.game_player.user_id == user.id).first()

    if not p or game.current_player_turn != p.turn_order:
        return {"error": "not_your_turn"}

    if game.has_rolled:
        return {"error": "already_rolled"}

    # 1. Бросаем кубики
    d1, d2 = random.randint(1, 6), random.randint(1, 6)
    steps = d1 + d2
    is_double = (d1 == d2)

    game.last_dice1 = d1
    game.last_dice2 = d2
    game.dice_roll_at = datetime.now(timezone.utc)
    game.has_rolled = True

    # --- ПРОВЕРКА НА 3 ДУБЛЯ ПОДРЯД (ТЫГЫДЫК) ---
    if is_double and not p.is_in_jail:
        p.doubles_count += 1
        if p.doubles_count >= 3:
            p.position = 10  # Карантин
            p.is_in_jail = True
            p.jail_turns = 0
            p.doubles_count = 0
            db.add(models.game_log(game_id=game_id, player_id=p.id,
                                   action_text="Котик разогнался до скорости света, снёс все вазы в доме и загремел на карантин за опасное вождение.",
                                   created_at=datetime.now(timezone.utc)))

            total_p = db.query(models.game_player).filter(models.game_player.game_id == game_id).count()
            game.current_player_turn = (game.current_player_turn % total_p) + 1
            game.has_rolled = False
            db.commit()
            return {"status": "jail_by_doubles"}
    elif not is_double:
        p.doubles_count = 0

    should_move = True

    # 2. Логика карантина
    if p.is_in_jail:
        if is_double:
            p.is_in_jail = False
            p.jail_turns = 0
            p.doubles_count = 0
            db.add(models.game_log(game_id=game_id, player_id=p.id,
                                   action_text=f"выбросил дубль ({d1}:{d2}) и выбежал из карантина!",
                                   created_at=datetime.now(timezone.utc)))
            should_move = True  # После дубля в тюрьме игрок СРАЗУ ходит
        else:
            p.jail_turns += 1
            if p.jail_turns >= 3:
                # Это была 3-я неудачная попытка. Игрок обязан заплатить и выйти.
                p.balance -= 50
                p.is_in_jail = False
                p.jail_turns = 0
                db.add(models.game_log(game_id=game_id, player_id=p.id,
                                       action_text=f"не выкинул дубль за 3 хода, заплатил $50 и вышел.",
                                       created_at=datetime.now(timezone.utc)))
                should_move = True  # И ходит на то, что выкинул
            else:
                db.add(models.game_log(game_id=game_id, player_id=p.id,
                                       action_text=f"остается в карантине (попытка {p.jail_turns}/3, выпало {d1}:{d2})",
                                       created_at=datetime.now(timezone.utc)))
                should_move = False
                # Конец хода, так как дубля нет и срок еще не вышел
                total_p = db.query(models.game_player).filter(models.game_player.game_id == game_id).count()
                game.current_player_turn = (game.current_player_turn % total_p) + 1
                game.has_rolled = False
                db.commit()
                return {"status": "still_in_jail", "dices": [d1, d2]}

    can_buy = False

    # 3. Движение
    if should_move:
        new_pos_raw = p.position + steps
        if new_pos_raw >= 40:
            p.balance += 200
            db.add(models.game_log(game_id=game_id, player_id=p.id, action_text="прошел круг и получил бонус (+200$)",
                                   created_at=datetime.now(timezone.utc)))

        p.position = new_pos_raw % 40
        cell = db.query(models.cells).filter(models.cells.id == p.position + 1).first()
        cell_name = cell.name if cell else "Неизвестное поле"

        db.add(models.game_log(game_id=game_id, player_id=p.id, action_text=f"встал на поле '{cell_name}'",
                               created_at=datetime.now(timezone.utc)))

        if "НА КАРАНТИН" in cell_name.upper():
            p.position = 10
            p.is_in_jail, p.jail_turns, p.doubles_count = True, 0, 0
            db.add(models.game_log(game_id=game_id, player_id=p.id,
                                   action_text="пойман на краже сосисок! Отправлен на карантин",
                                   created_at=datetime.now(timezone.utc)))
            can_buy = False
        else:
            ownership = db.query(models.property_ownership).filter(models.property_ownership.game_id == game_id,
                                                                   models.property_ownership.cell_id == cell.id).first()
            is_owned = (ownership is not None)
            buyable_types = ['property', 'station']
            can_buy = (cell and cell.type in buyable_types and cell.purchase_price > 0 and not is_owned)

            if is_owned and ownership.owner_id != p.id:
                # ЛОГИКА АРЕНДЫ
                if ownership.is_mortgaged:
                    db.add(models.game_log(game_id=game_id, player_id=p.id,
                                           action_text=f"не платит ренту за {cell.name}, так как поле в залоге",
                                           created_at=datetime.now(timezone.utc)))
                else:
                    owner_p = db.query(models.game_player).filter(models.game_player.id == ownership.owner_id).first()
                    if cell.type == 'station':
                        s_count = db.query(models.property_ownership).join(models.cells).filter(
                            models.property_ownership.game_id == game_id,
                            models.property_ownership.owner_id == owner_p.id,
                            models.cells.type == 'station'
                        ).count()
                        final_rent = int(cell.rent_base) * (2 ** (s_count - 1))
                    else:
                        multipliers = [1, 5, 15, 40, 70, 100]
                        final_rent = int(cell.rent_base) * multipliers[ownership.fish_count]

                    p.balance -= final_rent
                    owner_p.balance += final_rent
                    owner_u = db.query(models.users).filter(models.users.id == owner_p.user_id).first()
                    db.add(models.game_log(game_id=game_id, player_id=p.id,
                                           action_text=f"заплатил ренту ${final_rent} игроку {owner_u.username}",
                                           created_at=datetime.now(timezone.utc)))

            elif not can_buy:
                # --- ТВОИ ПОЛНЫЕ КОШАЧЬИ СОБЫТИЯ ---
                CAT_EVENTS = {
                    "TAX": {
                        "phrases": [
                            "уронил кактус, пришлось оплатить уборку",
                            "порвал занавески, штраф за порчу имущества",
                            "поточил когти об кожаный диван, ремонт обошелся дорого",
                            "сбросил хрустальную вазу «просто посмотреть, как она падает»",
                            "оставил шерсть на парадном костюме хозяина, оплатил химчистку",
                            "случайно съел дорогую орхидею, визит к ветеринару влетел в копеечку",
                            "застрял в жалюзи и сломал их, пришлось покупать новые",
                            "украл кусок сырого лосося, но его отобрали и вычли из бюджета"
                        ],
                        "money": -100
                    },
                    "CHANCE": {
                        "phrases": [
                            "нашел заначку под диваном",
                            "удачно поймал муху и получил награду",
                            "получил донат за красивое 'Мяу'",
                            "видео с твоим эпичным прыжком стало вирусным в соцсетях!",
                            "хозяин так расчувствовался от твоего мурчания, что дал бонус",
                            "удачно выкрал пакет лакомств из закрытого шкафа",
                            "победил в конкурсе на самый длинный хвост в районе",
                            "твоя фотография попала на упаковку корма, получен гонорар",
                            "нашел на ковре потерянную хозяйкой сережку и получил вознаграждение"
                        ],
                        "money": 50
                    },
                    "REST": {
                        "phrases": [
                            "нашел солнечное пятно и вздремнул",
                            "медитирует на птичек за окном",
                            "застрял в коробке и ни о чем не жалеет",
                            "свернулся идеальным калачиком и игнорирует зов хозяина",
                            "наблюдает за работой пылесоса из безопасного укрытия",
                            "пытается поймать собственный хвост, пока безуспешно",
                            "просто лежит и выглядит великолепно"
                        ],
                        "money": 0
                    },
                    "START": {
                        "phrases": [
                            "получил полную миску корма!",
                            "услышал звук открываемой банки тунца и примчался!",
                            "миска наполнилась сама собой по законам кошачьей магии",
                            "прошел круг и вытребовал вторую порцию завтрака",
                            "нашел в миске 'ту самую' вкусную подушечку"
                        ],
                        "money": 0
                    }
                }
                c_up = cell_name.upper()
                event_key = None
                if "СТАРТ" in c_up:
                    event_key = "START"
                elif any(x in c_up for x in ["НАЛОГ", "ШТРАФ", "СБОР"]):
                    event_key = "TAX"
                elif any(x in c_up for x in ["УДАЧА", "ШАНС", "ФОНД"]):
                    event_key = "CHANCE"
                elif any(x in c_up for x in ["ОТДЫХ", "ПАРКОВКА", "ЗОНА", "ФИЛЬТРАЦИИ", "ТЕПЛОЦЕНТРАЛЬ"]):
                    event_key = "REST"

                if event_key:
                    ev = CAT_EVENTS[event_key]
                    phrase, m_change = random.choice(ev["phrases"]), ev["money"]
                    p.balance += m_change
                    log_msg = f"{phrase} ({'+' if m_change > 0 else ''}{m_change}$)" if m_change != 0 else phrase
                    db.add(models.game_log(game_id=game_id, player_id=p.id, action_text=log_msg,
                                           created_at=datetime.now(timezone.utc)))

    # 4. Обработка конца хода
    if not should_move or not can_buy:
        # Уменьшаем таймер залога только если игрок реально заканчивает ход (не дубль)
        if not (is_double and not p.is_in_jail):
            my_mortgages = db.query(models.property_ownership).filter(
                models.property_ownership.game_id == game_id,
                models.property_ownership.owner_id == p.id,
                models.property_ownership.is_mortgaged == True
            ).all()
            for m in my_mortgages:
                m.mortgage_turns_left -= 1
                if m.mortgage_turns_left <= 0:
                    c_lost = db.query(models.cells).filter(models.cells.id == m.cell_id).first()
                    db.delete(m)
                    db.add(models.game_log(game_id=game_id, player_id=p.id,
                                           action_text=f"просрочил выкуп! Поле {c_lost.name} конфисковано.",
                                           created_at=datetime.now(timezone.utc)))

        if is_double and not p.is_in_jail:
            game.has_rolled = False
            db.add(models.game_log(game_id=game_id, player_id=p.id, action_text="Дубль! У котика еще одна попытка...",
                                   created_at=datetime.now(timezone.utc)))
        else:
            total_p = db.query(models.game_player).filter(models.game_player.game_id == game_id).count()
            game.current_player_turn = (game.current_player_turn % total_p) + 1
            game.has_rolled = False

    db.commit()
    return {"status": "ok"}

@app.get("/api/get_trade_info/{game_id}/{player_order}")
async def get_trade_info(game_id: int, player_order: int, db: Session = Depends(get_db)):
    """Возвращает список полей игрока с инфой о рыбках для окна обмена"""
    p = db.query(models.game_player).filter(
        models.game_player.game_id == game_id,
        models.game_player.turn_order == player_order
    ).first()

    if not p:
        return {"error": "not found"}

    # Получаем поля и количество рыбок на них через join
    props = db.query(models.cells, models.property_ownership.fish_count).join(
        models.property_ownership, models.cells.id == models.property_ownership.cell_id
    ).filter(
        models.property_ownership.game_id == game_id,
        models.property_ownership.owner_id == p.id
    ).all()

    return {
        "player_id": p.id,
        "username": db.query(models.users.username).filter(models.users.id == p.user_id).scalar(),
        # Добавляем fish_count в список объектов
        "properties": [{"id": pr[0].id, "name": pr[0].name, "fish": pr[1]} for pr in props]
    }


@app.post("/api/create_trade/{game_id}")
async def create_trade(
        game_id: int,
        recipient_id: int = Form(...),
        offer_money: int = Form(0),
        request_money: int = Form(0),
        offer_props: str = Form(""),
        request_props: str = Form(""),
        db: Session = Depends(get_db),
        user: models.users = Depends(get_current_user)
):
    # 1. Ищем игру и проверяем, существует ли она
    game = db.query(models.games).filter(models.games.id == game_id).first()
    if not game:
        return {"error": "Игра не найдена"}

    # 2. Ищем текущего игрока (отправителя)
    me = db.query(models.game_player).filter(
        models.game_player.game_id == game_id,
        models.game_player.user_id == user.id
    ).first()

    # 3. Проверка хода
    if not me or game.current_player_turn != me.turn_order:
        return {"error": "Сейчас не ваш ход"}

    # 4. ПРОВЕРКА НА ПУСТУЮ СДЕЛКУ (Нельзя отправить 0 денег и 0 полей)
    if offer_money == 0 and request_money == 0 and not offer_props and not request_props:
        return {"error": "Нельзя предложить абсолютно пустую сделку!"}

    # 5. Проверка на отрицательные суммы
    if offer_money < 0 or request_money < 0:
        return {"error": "Суммы денег не могут быть отрицательными"}

    # 6. Проверка баланса (есть ли у игрока столько денег, сколько он предлагает)
    if me.balance < offer_money:
        return {"error": "У вас недостаточно денег для такого предложения"}

    # 7. --- ПРОВЕРКА НА РЫБКИ (ЗАПРЕТ ОБМЕНА УЛУЧШЕННЫХ ПОЛЕЙ) ---
    all_props_ids = []
    if offer_props:
        all_props_ids.extend([int(x) for x in offer_props.split(",") if x])
    if request_props:
        all_props_ids.extend([int(x) for x in request_props.split(",") if x])

    if all_props_ids:
        # Проверяем, есть ли хотя бы одна рыбка на любом из вовлеченных в сделку полей
        upgraded = db.query(models.property_ownership).filter(
            models.property_ownership.game_id == game_id,
            models.property_ownership.cell_id.in_(all_props_ids),
            models.property_ownership.fish_count > 0
        ).first()

        if upgraded:
            return {"error": "Нельзя обмениваться полями, на которых есть рыбки. Сначала продайте улучшения!"}

    # 8. Удаляем старые висящие сделки от этого игрока (чтобы не спамить)
    db.query(models.trades).filter(
        models.trades.sender_id == me.id,
        models.trades.status == "pending"
    ).delete()

    # 9. Создаем новую запись сделки
    new_trade = models.trades(
        game_id=game_id,
        sender_id=me.id,
        recipient_id=recipient_id,
        offer_money=offer_money,
        request_money=request_money,
        offer_properties=offer_props,
        request_properties=request_props,
        status="pending"
    )
    db.add(new_trade)

    # 10. Получаем имя получателя для лога
    target_name = db.query(models.users.username).join(
        models.game_player, models.users.id == models.game_player.user_id
    ).filter(models.game_player.id == recipient_id).scalar()

    # 11. Добавляем запись в лог игры
    db.add(models.game_log(
        game_id=game_id,
        player_id=me.id,
        action_text=f"предложил сделку игроку {target_name}",
        created_at=datetime.now(timezone.utc)
    ))

    # 12. Сохраняем всё в базу
    db.commit()

    return {"status": "ok"}

@app.post("/api/create_trade/{game_id}")
async def create_trade(
        game_id: int, recipient_id: int = Form(...), offer_money: int = Form(0), request_money: int = Form(0),
        offer_props: str = Form(""), request_props: str = Form(""),
        db: Session = Depends(get_db), user: models.users = Depends(get_current_user)
):
    game = db.query(models.games).filter(models.games.id == game_id).first()
    me = db.query(models.game_player).filter(models.game_player.game_id == game_id,
                                             models.game_player.user_id == user.id).first()
    if not me or game.current_player_turn != me.turn_order:
        return {"error": "сейчас не ваш ход"}

    # СЕРВЕРНАЯ ПРОВЕРКА НА ОТРИЦАТЕЛЬНЫЕ ДЕНЬГИ
    if offer_money < 0 or request_money < 0:
        return {"error": "нельзя использовать отрицательные суммы денег"}

    # Проверка, есть ли у игрока столько денег, сколько он предлагает
    if me.balance < offer_money:
        return {"error": "у вас нет столько денег для предложения"}

    # Удаляем старые висящие сделки от этого игрока
    db.query(models.trades).filter(models.trades.sender_id == me.id, models.trades.status == "pending").delete()

    new_trade = models.trades(
        game_id=game_id, sender_id=me.id, recipient_id=recipient_id,
        offer_money=offer_money, request_money=request_money,
        offer_properties=offer_props, request_properties=request_props,
        status="pending"
    )
    db.add(new_trade)

    target_name = db.query(models.users.username).join(models.game_player).filter(
        models.game_player.id == recipient_id).scalar()

    db.add(models.game_log(game_id=game_id, player_id=me.id,
                           action_text=f"предложил сделку игроку {target_name}",
                           created_at=datetime.now(timezone.utc)))

    db.commit()
    return {"status": "ok"}


@app.post("/api/respond_trade/{game_id}/{trade_id}/{action}")
async def respond_trade(
        game_id: int,
        trade_id: int,
        action: str,
        db: Session = Depends(get_db),
        user: models.users = Depends(get_current_user)
):
    # 1. Ищем сделку
    trade = db.query(models.trades).filter(models.trades.id == trade_id).first()
    if not trade or trade.status != "pending":
        return {"error": "Сделка не найдена или уже обработана"}

    # 2. Проверяем, что именно этот юзер — получатель сделки
    # (Ищем запись игрока в этой игре)
    me = db.query(models.game_player).filter(
        models.game_player.id == trade.recipient_id,
        models.game_player.user_id == user.id
    ).first()

    if not me:
        return {"error": "Вы не являетесь получателем этой сделки"}

    # Ищем отправителя
    sender_p = db.query(models.game_player).filter(models.game_player.id == trade.sender_id).first()
    sender_u = db.query(models.users).filter(models.users.id == sender_p.user_id).first()
    sender_name = sender_u.username

    if action == "accept":
        # 3. ПРОВЕРКА ДЕНЕГ перед окончательным принятием
        if sender_p.balance < trade.offer_money:
            trade.status = "declined"
            db.commit()
            return {"error": f"У {sender_name} уже нет столько денег!"}

        if me.balance < trade.request_money:
            return {"error": "У вас недостаточно денег для этой сделки"}

        # 4. СОБИРАЕМ НАЗВАНИЯ ПОЛЕЙ ДЛЯ ЛОГА (до смены владельцев)
        offer_prop_names = []
        if trade.offer_properties:
            off_ids = [int(x) for x in trade.offer_properties.split(",") if x]
            offer_prop_names = [n[0] for n in db.query(models.cells.name).filter(models.cells.id.in_(off_ids)).all()]

        req_prop_names = []
        if trade.request_properties:
            req_ids = [int(x) for x in trade.request_properties.split(",") if x]
            req_prop_names = [n[0] for n in db.query(models.cells.name).filter(models.cells.id.in_(req_ids)).all()]

        # 5. ПРОВОДИМ ОБМЕН ДЕНЬГАМИ
        sender_p.balance -= trade.offer_money
        me.balance += trade.offer_money

        me.balance -= trade.request_money
        sender_p.balance += trade.request_money

        # 6. ПЕРЕПИСЫВАЕМ ВЛАДЕЛЬЦЕВ ПОЛЕЙ
        if trade.offer_properties:
            off_ids = [int(x) for x in trade.offer_properties.split(",") if x]
            db.query(models.property_ownership).filter(
                models.property_ownership.game_id == game_id,
                models.property_ownership.cell_id.in_(off_ids)
            ).update({"owner_id": me.id}, synchronize_session=False)

        if trade.request_properties:
            req_ids = [int(x) for x in trade.request_properties.split(",") if x]
            db.query(models.property_ownership).filter(
                models.property_ownership.game_id == game_id,
                models.property_ownership.cell_id.in_(req_ids)
            ).update({"owner_id": sender_p.id}, synchronize_session=False)

        trade.status = "accepted"

        # 7. ФОРМИРУЕМ ПОДРОБНЫЙ ЛОГ
        received_by_me = f"${trade.offer_money}"
        if offer_prop_names: received_by_me += f" и поля {', '.join(offer_prop_names)}"

        received_by_sender = f"${trade.request_money}"
        if req_prop_names: received_by_sender += f" и поля {', '.join(req_prop_names)}"

        log_msg = (f"совершил обмен с {sender_name}. "
                   f"{user.username} получил {received_by_me}, "
                   f"а {sender_name} получил {received_by_sender}")

        db.add(models.game_log(
            game_id=game_id, player_id=me.id,
            action_text=log_msg, created_at=datetime.now(timezone.utc)
        ))
    else:
        # Если отклонили
        trade.status = "declined"
        db.add(models.game_log(
            game_id=game_id, player_id=me.id,
            action_text=f"ОТКЛОНИЛ сделку игрока {sender_name}",
            created_at=datetime.now(timezone.utc)
        ))

    db.commit()
    return {"status": "ok"}

@app.post("/api/mortgage_property/{game_id}/{cell_id}")
async def mortgage_property(game_id: int, cell_id: int, db: Session = Depends(get_db), user: models.users = Depends(get_current_user)):
    game, p = db.query(models.games).filter(models.games.id == game_id).first(), db.query(models.game_player).filter(models.game_player.game_id == game_id, models.game_player.user_id == user.id).first()
    if not p or game.current_player_turn != p.turn_order: return {"error": "not_your_turn"}

    own = db.query(models.property_ownership).filter(models.property_ownership.game_id == game_id, models.property_ownership.cell_id == cell_id, models.property_ownership.owner_id == p.id).first()
    if not own or own.is_mortgaged or own.fish_count > 0: return {"error": "нельзя заложить (есть рыбки или уже в залоге)"}

    cell = db.query(models.cells).filter(models.cells.id == cell_id).first()
    mortgage_value = int(float(cell.purchase_price) * 0.5) # Получаем 50% стоимости

    p.balance += mortgage_value
    own.is_mortgaged = True
    own.mortgage_turns_left = 10 # Устанавливаем срок на 10 раундов

    db.add(models.game_log(game_id=game_id, player_id=p.id, action_text=f"заложил {cell.name} и получил ${mortgage_value}", created_at=datetime.now(timezone.utc)))
    db.commit()
    return {"success": True}

@app.post("/api/unmortgage_property/{game_id}/{cell_id}")
async def unmortgage_property(game_id: int, cell_id: int, db: Session = Depends(get_db), user: models.users = Depends(get_current_user)):
    game, p = db.query(models.games).filter(models.games.id == game_id).first(), db.query(models.game_player).filter(models.game_player.game_id == game_id, models.game_player.user_id == user.id).first()
    if not p or game.current_player_turn != p.turn_order: return {"error": "not_your_turn"}

    own = db.query(models.property_ownership).filter(models.property_ownership.game_id == game_id, models.property_ownership.cell_id == cell_id, models.property_ownership.owner_id == p.id).first()
    if not own or not own.is_mortgaged: return {"error": "поле не в залоге"}

    cell = db.query(models.cells).filter(models.cells.id == cell_id).first()
    # Выкуп стоит 50% + 10% налога (итого 60% от цены покупки)
    unmortgage_cost = int(float(cell.purchase_price) * 0.6)

    if p.balance >= unmortgage_cost:
        p.balance -= unmortgage_cost
        own.is_mortgaged = False
        own.mortgage_turns_left = 10
        db.add(models.game_log(game_id=game_id, player_id=p.id, action_text=f"выкупил {cell.name} из залога за ${unmortgage_cost}", created_at=datetime.now(timezone.utc)))
        db.commit()
        return {"success": True}
    return {"error": "недостаточно денег для выкупа"}


@app.get("/api/game_state/{game_id}")
async def get_game_state(game_id: int, db: Session = Depends(get_db), user: models.users = Depends(get_current_user)):
    # 1. Ищем саму игру
    game = db.query(models.games).filter(models.games.id == game_id).first()
    if not game:
        return {"status": "error", "message": "Игра не найдена"}

    # 2. Получаем список всех активных игроков (те, кто еще в матче), сортируем по порядку хода
    players_query = db.query(models.users, models.game_player).join(
        models.game_player, models.users.id == models.game_player.user_id
    ).filter(models.game_player.game_id == game_id).order_by(models.game_player.turn_order).all()

    # --- ЛОГИКА АВТО-БАНКРОТСТВА (МГНОВЕННЫЙ ВЫЛЕТ И ПЕРЕДАЧА ИМУЩЕСТВА) ---
    bankrupt_detected = False
    for u_entry, p_entry in players_query:
        if p_entry.balance < 0:
            bankrupt_id = p_entry.id
            bankrupt_order = p_entry.turn_order
            bankrupt_name = u_entry.username

            # --- НОВЫЙ БЛОК: ОПРЕДЕЛЕНИЕ КТО ВЫКИНУЛ ИГРОКА ---
            # Проверяем, стоит ли игрок на чужом поле
            current_cell_id = p_entry.position + 1
            ownership_on_cell = db.query(models.property_ownership).filter(
                models.property_ownership.game_id == game_id,
                models.property_ownership.cell_id == current_cell_id
            ).first()

            killer_id = None
            # Если на этой клетке есть владелец и это не сам банкрот
            if ownership_on_cell and ownership_on_cell.owner_id != bankrupt_id:
                killer_id = ownership_on_cell.owner_id

            if killer_id:
                # Находим данные "убийцы" для лога
                killer_p = db.query(models.game_player).filter(models.game_player.id == killer_id).first()
                killer_u = db.query(models.users).filter(models.users.id == killer_p.user_id).first()

                # ПЕРЕДАЕМ ВСЕ ПОЛЯ БАНКРОТА НОВОМУ ВЛАДЕЛЬЦУ
                db.query(models.property_ownership).filter(
                    models.property_ownership.game_id == game_id,
                    models.property_ownership.owner_id == bankrupt_id
                ).update({
                    "owner_id": killer_id,
                    "fish_count": 0,       # Рыбки (дома) сгорают при конфискации
                    "is_mortgaged": False  # Поля выходят из залога
                }, synchronize_session=False)

                action_msg = f"стал банкротом! Все его миски и поля перешли к котику {killer_u.username}."
            else:
                # А) Если "убийцы" нет (банкротство об налог или банк), возвращаем поля банку
                db.query(models.property_ownership).filter(
                    models.property_ownership.game_id == game_id,
                    models.property_ownership.owner_id == bankrupt_id
                ).delete()
                action_msg = f"стал банкротом! Его миски пусты, а имущество вернулось в приют (банк)."

            # Б) Добавляем запись в лог игры
            db.add(models.game_log(
                game_id=game_id,
                player_id=bankrupt_id,
                action_text=action_msg,
                created_at=datetime.now(timezone.utc)
            ))

            # В) Если сейчас был ход именно этого игрока — переключаем ход на СЛЕДУЮЩЕГО
            if game.current_player_turn == bankrupt_order:
                remaining_orders = [pl[1].turn_order for pl in players_query if pl[1].id != bankrupt_id]
                if remaining_orders:
                    next_potential = [o for o in remaining_orders if o > bankrupt_order]
                    if next_potential:
                        game.current_player_turn = min(next_potential)
                    else:
                        game.current_player_turn = min(remaining_orders)
                game.has_rolled = False

            # Г) Удаляем игрока и все его висящие сделки
            db.query(models.trades).filter(
                (models.trades.sender_id == bankrupt_id) | (models.trades.recipient_id == bankrupt_id)
            ).delete()

            db.delete(p_entry)
            db.commit()

            bankrupt_detected = True
            break  # Прерываем, чтобы обновить список рекурсивно

    if bankrupt_detected:
        return await get_game_state(game_id, db, user)

    # --- ЛОГИКА ЗАВЕРШЕНИЯ ИГРЫ ---
    if len(players_query) == 1 and game.status == "playing":
        game.status = "finished"
        winner_u, winner_p = players_query[0]
        game.winner_id = winner_u.id
        game.finished_at = datetime.now(timezone.utc)
        db.commit()

    if game.status == "finished":
        winner_u = db.query(models.users).filter(models.users.id == game.winner_id).first()
        return {
            "status": "finished",
            "winner_name": winner_u.username if winner_u else "Котик-невидимка",
            "winner_avatar": winner_u.avatar_url if winner_u and winner_u.avatar_url else "/static/default_cat.png",
            "winner_id": game.winner_id,
            "my_id": user.id if user else 0
        }

    # --- СБОР ДАННЫХ ВЛАДЕНИЯ ---
    ownerships_raw = db.query(models.property_ownership).filter(models.property_ownership.game_id == game_id).all()
    owner_map = {}
    fish_map = {}
    mort_map = {}

    for o in ownerships_raw:
        p_order = db.query(models.game_player.turn_order).filter(models.game_player.id == o.owner_id).scalar()
        if p_order:
            owner_map[o.cell_id] = p_order
            fish_map[o.cell_id] = o.fish_count
            mort_map[o.cell_id] = {
                "is_mortgaged": o.is_mortgaged,
                "turns_left": o.mortgage_turns_left
            }

    # Логи и Чат
    logs = db.query(models.users.username, models.game_log.action_text).join(
        models.game_player, models.game_log.player_id == models.game_player.id
    ).join(models.users, models.game_player.user_id == models.users.id).filter(
        models.game_log.game_id == game_id
    ).order_by(models.game_log.id.desc()).limit(15).all()

    chat = db.query(models.game_chat, models.users.username).join(models.users).filter(
        models.game_chat.game_id == game_id
    ).order_by(models.game_chat.id.asc()).all() # Убрал лимит как просил

    # --- ЛОГИКА ТЕКУЩЕГО ИГРОКА (ПОКУПКА И СДЕЛКИ) ---
    me = db.query(models.game_player).filter(
        models.game_player.game_id == game_id,
        models.game_player.user_id == (user.id if user else 0)
    ).first()

    can_buy_now = False
    cell_info = {}
    incoming_trade_data = None

    if me:
        if game.current_player_turn == me.turn_order and game.has_rolled:
            current_cell = db.query(models.cells).filter(models.cells.id == me.position + 1).first()
            if current_cell:
                is_owned = db.query(models.property_ownership).filter(
                    models.property_ownership.game_id == game_id,
                    models.property_ownership.cell_id == current_cell.id
                ).first()
                if current_cell.type in ['property', 'station'] and not is_owned:
                    can_buy_now = True
                    cell_info = {"name": current_cell.name, "price": int(current_cell.purchase_price)}

        trade = db.query(models.trades).filter(
            models.trades.game_id == game_id,
            models.trades.recipient_id == me.id,
            models.trades.status == "pending"
        ).first()

        if trade:
            off_ids = [int(x) for x in trade.offer_properties.split(",") if x] if trade.offer_properties else []
            req_ids = [int(x) for x in trade.request_properties.split(",") if x] if trade.request_properties else []
            off_names = [n[0] for n in db.query(models.cells.name).filter(models.cells.id.in_(off_ids)).all()]
            req_names = [n[0] for n in db.query(models.cells.name).filter(models.cells.id.in_(req_ids)).all()]
            sender_u = db.query(models.users.username).join(models.game_player).filter(
                models.game_player.id == trade.sender_id).scalar()

            incoming_trade_data = {
                "id": trade.id,
                "sender_name": sender_u,
                "offer_money": trade.offer_money,
                "request_money": trade.request_money,
                "offer_prop_names": ", ".join(off_names),
                "request_prop_names": ", ".join(req_names)
            }

    return {
        "status": "playing",
        "current_turn": game.current_player_turn,
        "last_dice": [game.last_dice1, game.last_dice2],
        "dice_roll_at": game.dice_roll_at.isoformat() if game.dice_roll_at else None,
        "players": [
            {
                "name": p[0].username,
                "pos": p[1].position,
                "order": p[1].turn_order,
                "money": int(p[1].balance),
                "is_in_jail": p[1].is_in_jail
            } for p in players_query
        ],
        "ownerships": owner_map,
        "fish_levels": fish_map,
        "mortgages": mort_map,
        "logs": [f"{l[0]} {l[1]}" for l in logs],
        "chat": [{"name": c[1], "text": c[0].message} for c in chat],
        "can_buy_now": can_buy_now,
        "current_cell_data": cell_info,
        "incoming_trade": incoming_trade_data,
        "my_id": user.id if user else 0
    }

@app.post("/api/buy_property/{game_id}")
async def buy_property(game_id: int, db: Session = Depends(get_db), user: models.users = Depends(get_current_user)):
    game, p = db.query(models.games).filter(models.games.id == game_id).first(), db.query(models.game_player).filter(
        models.game_player.game_id == game_id, models.game_player.user_id == user.id).first()

    if not p or game.current_player_turn != p.turn_order: return {"error": "not_your_turn"}

    cell = db.query(models.cells).filter(models.cells.id == p.position + 1).first()

    if cell and cell.type in ['property', 'station'] and p.balance >= cell.purchase_price:
        p.balance -= cell.purchase_price
        db.add(models.property_ownership(game_id=game_id, cell_id=cell.id, owner_id=p.id))
        db.add(models.game_log(game_id=game_id, player_id=p.id, action_text=f"купил {cell.name}",
                               created_at=datetime.now(timezone.utc)))

        # ЛОГИКА ДУБЛЯ: если был дубль, даем кинуть еще раз вместо перехода хода
        if game.last_dice1 == game.last_dice2:
            game.has_rolled = False
            db.add(models.game_log(game_id=game_id, player_id=p.id, action_text="Дубль! Можешь кинуть кубики еще раз.",
                                   created_at=datetime.now(timezone.utc)))
        else:
            total_p = db.query(models.game_player).filter(models.game_player.game_id == game_id).count()
            game.current_player_turn = (game.current_player_turn % total_p) + 1
            game.has_rolled = False

        db.commit()
        return {"success": True}
    return {"error": "cannot_buy"}


@app.get("/api/check_game_status")
async def check_status(db: Session = Depends(get_db), user: models.users = Depends(get_current_user)):
    if not user: return {"status": "none"}

    # Ищем игру, где мы всё еще в таблице игроков
    entry = db.query(models.game_player).filter(
        models.game_player.user_id == user.id
    ).join(models.games).filter(models.games.status == "playing").first()

    if entry:
        return {"status": "playing", "game_id": entry.game_id}

    return {"status": "none"}


@app.post("/api/skip_buy/{game_id}")
async def skip_buy(game_id: int, db: Session = Depends(get_db), user: models.users = Depends(get_current_user)):
    game, p = db.query(models.games).filter(models.games.id == game_id).first(), db.query(models.game_player).filter(
        models.game_player.game_id == game_id, models.game_player.user_id == user.id).first()

    if p and game.current_player_turn == p.turn_order:
        if game.last_dice1 == game.last_dice2:
            # Был дубль — даем кинуть снова
            game.has_rolled = False
            db.add(models.game_log(game_id=game_id, player_id=p.id,
                                   action_text="Пропустил покупку, но из-за дубля кидает снова!",
                                   created_at=datetime.now(timezone.utc)))
        else:
            total_p = db.query(models.game_player).filter(models.game_player.game_id == game_id).count()
            game.current_player_turn = (game.current_player_turn % total_p) + 1
            game.has_rolled = False
        db.commit()
    return {"status": "ok"}

# --- ЛОГИКА ДРУЗЕЙ ---

@app.get("/api/friends", response_class=HTMLResponse)
async def read_friends(request: Request, db: Session = Depends(get_db), user: models.users = Depends(get_current_user),
                       search_query: str = ""):
    if not user: return RedirectResponse("/login")

    results = []
    if search_query:
        raw = db.query(models.users).filter(models.users.username.ilike(f"%{search_query}%"),
                                            models.users.id != user.id).all()
        for p in raw:
            rel = db.query(models.friendships).filter(
                ((models.friendships.user_id == user.id) & (models.friendships.friend_id == p.id)) |
                ((models.friendships.user_id == p.id) & (models.friendships.friend_id == user.id))
            ).first()
            results.append({"user": p, "status": rel.status if rel else None})

    incoming = db.query(models.users).join(models.friendships, models.users.id == models.friendships.user_id).filter(
        models.friendships.friend_id == user.id, models.friendships.status == "pending"
    ).all()

    f1 = [f[0] for f in db.query(models.friendships.friend_id).filter(models.friendships.user_id == user.id,
                                                                      models.friendships.status == "accepted").all()]
    f2 = [f[0] for f in db.query(models.friendships.user_id).filter(models.friendships.friend_id == user.id,
                                                                    models.friendships.status == "accepted").all()]
    my_friends = db.query(models.users).filter(models.users.id.in_(f1 + f2)).all()

    ctx = get_base_context(request, user, db)
    ctx.update({
        "current_page": "/api/friends",
        "friends": my_friends,
        "incoming": incoming,
        "search_results": results,
        "query": search_query
    })
    return templates.TemplateResponse(request=request, name="friends.html", context=ctx)


@app.get("/send_request/{friend_id}")
async def send_request(friend_id: int, db: Session = Depends(get_db), user: models.users = Depends(get_current_user)):
    if not user: return RedirectResponse("/login")
    exists = db.query(models.friendships).filter(
        ((models.friendships.user_id == user.id) & (models.friendships.friend_id == friend_id)) |
        ((models.friendships.user_id == friend_id) & (models.friendships.friend_id == user.id))
    ).first()
    if not exists:
        db.add(models.friendships(user_id=user.id, friend_id=friend_id))
        db.commit()
    return RedirectResponse(url="/api/friends")


@app.get("/accept_friend/{rid}")
async def accept_friend(rid: int, db: Session = Depends(get_db), user: models.users = Depends(get_current_user)):
    req = db.query(models.friendships).filter(models.friendships.user_id == rid,
                                              models.friendships.friend_id == user.id).first()
    if req:
        req.status = "accepted"
        db.commit()
    return RedirectResponse(url="/api/friends")


@app.get("/delete_friend/{fid}")
async def delete_friend(fid: int, db: Session = Depends(get_db), user: models.users = Depends(get_current_user)):
    f = db.query(models.friendships).filter(
        ((models.friendships.user_id == user.id) & (models.friendships.friend_id == fid)) |
        ((models.friendships.user_id == fid) & (models.friendships.friend_id == user.id))
    ).first()
    if f:
        db.delete(f)
        db.commit()
    return RedirectResponse(url="/api/friends")


# --- ИНВАЙТЫ ---

@app.get("/send_invite/{friend_id}")
async def send_invite(friend_id: int, db: Session = Depends(get_db), user: models.users = Depends(get_current_user)):
    lobby = db.query(models.games).filter(models.games.owner_id == user.id, models.games.status == "waiting").first()
    if lobby:
        db.add(models.invitations(sender_id=user.id, recipient_id=friend_id, game_id=lobby.id))
        db.commit()
    return RedirectResponse("/api/search")


@app.get("/accept_invite/{invite_id}")
async def accept_invite(invite_id: int, db: Session = Depends(get_db), user: models.users = Depends(get_current_user)):
    inv = db.query(models.invitations).filter(models.invitations.id == invite_id,
                                              models.invitations.recipient_id == user.id).first()
    if inv:
        inv.status = "accepted"
        db.commit()
        return RedirectResponse(f"/join_lobby/{inv.game_id}")
    return RedirectResponse("/")


@app.get("/decline_invite/{invite_id}")
async def decline_invite(invite_id: int, db: Session = Depends(get_db), user: models.users = Depends(get_current_user)):
    inv = db.query(models.invitations).filter(models.invitations.id == invite_id,
                                              models.invitations.recipient_id == user.id).first()
    if inv:
        db.delete(inv)
        db.commit()
    return RedirectResponse("/")


# --- ПРОФИЛИ ---

@app.get("/profile")
async def profile_redirect(user: models.users = Depends(get_current_user)):
    if not user: return RedirectResponse("/login")
    return RedirectResponse(f"/profile/{user.id}")


@app.get("/profile/{user_id}", response_class=HTMLResponse)
async def view_profile(user_id: int, request: Request, db: Session = Depends(get_db),
                       user: models.users = Depends(get_current_user)):
    if not user:
        return RedirectResponse("/login")

    target = db.query(models.users).filter(models.users.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404)

    is_own = (user.id == target.id)

    # 1. Считаем друзей
    f_c = db.query(models.friendships).filter(
        (models.friendships.status == "accepted") &
        ((models.friendships.user_id == user_id) | (models.friendships.friend_id == user_id))
    ).count()

    # 2. Считаем матчи
    m_c = db.query(models.game_player).filter(models.game_player.user_id == user_id).count()

    # 3. Считаем победы
    w_c = db.query(models.games).filter(models.games.winner_id == user_id).count()

    # Ссылка на аватар
    display_avatar = target.avatar_url if target.avatar_url else "/static/default_cat.png"

    ctx = get_base_context(request, user, db)
    ctx.update({
        "username": target.username,
        "avatar_url": display_avatar,
        "created_at": target.created_at.strftime("%d %B %Y") if target.created_at else "неизвестно",
        "is_own_profile": is_own,
        "friends_count": f_c,
        "matches_count": m_c,
        "wins_count": w_c,
        "current_page": "/profile" if is_own else ""
    })
    return templates.TemplateResponse(request=request, name="profile.html", context=ctx)


@app.post("/upload_avatar")
async def upload_avatar(file: UploadFile = File(...), db: Session = Depends(get_db),
                        user: models.users = Depends(get_current_user)):
    if not user:
        return RedirectResponse("/login")

    try:
        # Получаем расширение и переводим в нижний регистр
        ext = file.filename.split(".")[-1].lower()
        fname = f"user_{user.id}.{ext}"

        # Проверяем путь к папке (создаем если нет)
        os.makedirs(UPLOAD_DIR / "avatars", exist_ok=True)
        path = UPLOAD_DIR / "avatars" / fname

        with open(path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Обновляем запись в базе
        u_db = db.query(models.users).filter(models.users.id == user.id).first()
        # Ставим метку времени v=, чтобы браузер не кешировал картинку
        u_db.avatar_url = f"/uploads/avatars/{fname}?v={int(datetime.now().timestamp())}"

        db.commit()
    except Exception as e:
        print(f"ОШИБКА ЗАГРУЗКИ: {e}")
        return {"error": "failed to upload"}

    return RedirectResponse("/profile", status_code=303)


@app.post("/api/upgrade_property/{game_id}/{cell_id}")
async def upgrade_property(game_id: int, cell_id: int, db: Session = Depends(get_db),
                           user: models.users = Depends(get_current_user)):
    game = db.query(models.games).filter(models.games.id == game_id).first()
    p = db.query(models.game_player).filter(models.game_player.game_id == game_id,
                                            models.game_player.user_id == user.id).first()

    if not p or game.current_player_turn != p.turn_order:
        return {"error": "Сейчас не твой ход!"}

    # 1. Ищем клетку, которую хотим улучшить
    cell = db.query(models.cells).filter(models.cells.id == cell_id).first()
    if not cell or cell.type != 'property':
        return {"error": "Это поле нельзя улучшать рыбками"}

    # 2. Проверяем владение
    ownership = db.query(models.property_ownership).filter(
        models.property_ownership.game_id == game_id,
        models.property_ownership.cell_id == cell_id,
        models.property_ownership.owner_id == p.id
    ).first()

    if not ownership:
        return {"error": "Это не твоё поле!"}

    if ownership.is_mortgaged:
        return {"error": "Нельзя улучшать заложенное поле!"}

    # --- НОВАЯ ЛОГИКА: ПРОВЕРКА ЦВЕТОВОЙ ГРУППЫ ---

    # Считаем, сколько всего полей этого цвета в игре
    total_color_fields = db.query(models.cells).filter(models.cells.color_group == cell.color_group).count()

    # Считаем, сколькими из них владеет игрок
    owned_color_fields = db.query(models.property_ownership).join(models.cells).filter(
        models.property_ownership.game_id == game_id,
        models.property_ownership.owner_id == p.id,
        models.cells.color_group == cell.color_group
    ).count()

    if owned_color_fields < total_color_fields:
        return {"error": f"Сначала собери все поля цвета {cell.color_group}, чтобы покупать рыбки!"}

    # --- КОНЕЦ ПРОВЕРКИ ---

    if ownership.fish_count >= 5:
        return {"error": "Достигнут максимальный уровень уюта (5 рыбок)!"}

    # Цена улучшения (50% от цены покупки)
    upgrade_price = int(float(cell.purchase_price) * 0.5)

    if p.balance >= upgrade_price:
        p.balance -= upgrade_price
        ownership.fish_count += 1

        db.add(models.game_log(
            game_id=game_id,
            player_id=p.id,
            action_text=f"улучшил поле {cell.name} (теперь тут {ownership.fish_count} 🐟)",
            created_at=datetime.now(timezone.utc)
        ))
        db.commit()
        return {"success": True, "new_level": ownership.fish_count}

    return {"error": "Недостаточно денег для покупки рыбки"}

@app.post("/api/sell_fish/{game_id}/{cell_id}")
async def sell_fish(game_id: int, cell_id: int, db: Session = Depends(get_db), user: models.users = Depends(get_current_user)):
    game, p = db.query(models.games).filter(models.games.id == game_id).first(), db.query(models.game_player).filter(models.game_player.game_id == game_id, models.game_player.user_id == user.id).first()
    if not p or game.current_player_turn != p.turn_order: return {"error": "not_your_turn"}

    own = db.query(models.property_ownership).filter(models.property_ownership.game_id == game_id, models.property_ownership.cell_id == cell_id, models.property_ownership.owner_id == p.id).first()
    if not own or own.fish_count <= 0: return {"error": "на поле нет рыбок"}

    cell = db.query(models.cells).filter(models.cells.id == cell_id).first()
    # Возвращаем 50% от стоимости улучшения (которое само 50% от цены поля)
    # То есть игрок получает 25% от покупной цены за продажу одной рыбки
    refund = int(float(cell.purchase_price) * 0.25)

    p.balance += refund
    own.fish_count -= 1

    db.add(models.game_log(game_id=game_id, player_id=p.id, action_text=f"продал рыбку с поля {cell.name} и получил ${refund}", created_at=datetime.now(timezone.utc)))
    db.commit()
    return {"success": True}

@app.get("/api/user_sync")
async def user_sync(db: Session = Depends(get_db), user: models.users = Depends(get_current_user)):
    if not user: return {"status": "unauthorized"}

    # Проверяем игру, в которой юзер реально числится игроком
    active_game = db.query(models.games).join(models.game_player).filter(
        models.game_player.user_id == user.id,
        models.games.status == "playing"
    ).first()

    invites_count = db.query(models.invitations).filter(
        models.invitations.recipient_id == user.id,
        models.invitations.status == "pending"
    ).count()

    lobbies_count = db.query(models.games).filter(models.games.status == "waiting").count()

    return {
        "status": "ok",
        "active_game_id": active_game.id if active_game else None,
        "invites_count": invites_count,
        "lobbies_count": lobbies_count
    }

# --- ПОЛЯ ---

@app.get("/api/fields", response_class=HTMLResponse)
async def read_fields(request: Request, db: Session = Depends(get_db), user: models.users = Depends(get_current_user)):
    if not user: return RedirectResponse("/login")
    ctx = get_base_context(request, user, db)
    ctx["current_page"] = "/api/fields"
    return templates.TemplateResponse(request=request, name="fields.html", context=ctx)