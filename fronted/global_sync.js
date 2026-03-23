// Функция для проверки состояния игрока (инвайты, лобби, активная игра)
async function checkUserGlobalStatus() {
    try {
        const response = await fetch('/api/user_sync');
        if (!response.ok) return;

        const data = await response.json();
        const currentPath = window.location.pathname;

        if (data.status === 'ok') {
            // 1. ПРОВЕРКА АКТИВНОЙ ИГРЫ
            // Если сервер говорит, что мы в игре, но мы не на странице игры — перекидываем туда
            if (data.active_game_id && !currentPath.includes('/game/')) {
                console.log("Обнаружена активная игра! Перенаправление...");
                window.location.href = `/game/${data.active_game_id}`;
                return; // Дальше код не выполняем
            }

            // 2. СИНХРОНИЗАЦИЯ ЛОББИ И ИНВАЙТОВ
            // Достаем старые значения из памяти браузера
            const lastLobbies = sessionStorage.getItem('last_lobbies_count');
            const lastInvites = sessionStorage.getItem('last_invites_count');

            // Превращаем в числа (или ставим null, если их еще нет)
            const oldLobbies = lastLobbies !== null ? parseInt(lastLobbies) : null;
            const oldInvites = lastInvites !== null ? parseInt(lastInvites) : null;

            let needReload = false;

            // Если количество лобби изменилось и мы на странице поиска
            if (oldLobbies !== null && oldLobbies !== data.lobbies_count) {
                if (currentPath.includes('/api/search')) {
                    console.log("Список лобби обновился");
                    needReload = true;
                }
            }

            // Если количество инвайтов изменилось (пришел новый или удалили старый)
            if (oldInvites !== null && oldInvites !== data.invites_count) {
                console.log("Количество инвайтов изменилось");
                needReload = true;
            }

            // Сначала СОХРАНЯЕМ новые данные, чтобы при перезагрузке условие не сработало снова
            sessionStorage.setItem('last_lobbies_count', data.lobbies_count);
            sessionStorage.setItem('last_invites_count', data.invites_count);

            // И только теперь перезагружаем, если это нужно
            if (needReload) {
                console.log("Перезагрузка страницы для синхронизации данных...");
                location.reload();
            }
        }
    } catch (e) {
        console.error("Ошибка глобальной синхронизации:", e);
    }
}

// Запускаем проверку каждые 3 секунды
setInterval(checkUserGlobalStatus, 3000);

// Вызываем один раз сразу при загрузке, чтобы инициализировать значения в sessionStorage
checkUserGlobalStatus();