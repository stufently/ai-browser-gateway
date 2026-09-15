# M12 — разведка сервиса, пула и deployed-прогона

Исполнитель подготовки — явный Grok; только разведка, без реализации.
BASE_SHA: 92d8ad51d322400d469ef485b7cabb7ed7426e38.
Клон: /home/user/exec-clones/abg-m12-recon-20260915.
Выход: /home/user/.cache/abg-coord-20260915/m12/recon-result.md
и соседние evidence-файлы; короткий итог с manifest SHA256.

M11 принята владельцем15.09 на FINAL e6f7f0c и опубликована merge e5fd997.
Повторять приёмку M9–M11, tests/reviews/mutations/бенчмарк НЕ нужно.
Возврат после VERIFY_ONLY впредь — новая веха с BASE прежнего FINAL.
Spark исчерпан до20.09 15:59, timezone неизвестен; Grok reset подтверждён
владельцем15.09, фактические окна5h/weekly неизвестны. Не запускать других
моделей; quota error сохранить и остановиться без повторов.

Прочитай TASKS.md M12 и исходное поручение:
/home/user/gitlab/9qw/tg-claude-userbot/tmp/abg-coord-task-20260914.md.
Используй готовые факты, не повторяй всю разведку:
/home/user/.cache/abg-coord-20260914/service-monitoring-notes.md
/home/user/.cache/abg-coord-20260914/egress-readiness-result.md
/home/user/.cache/abg-coord-20260914/m10-recon-result.md.

Дай факты/неизвестное и минимальное предложение для execution-спеки:
1. Точные точки подключения принятого API к сервису: запуск, token/config,
   глобальный browser limit, health endpoint, пул proxy profiles; чего ещё нет.
   Версионный RO release на ОДИНАКОВОМ абсолютном пути host/API позволяет
   сохранить принятый PROBE_FILE. Покажи конкретные mounts/working_dir/env,
   docker socket только API, никогда провайдерам/monitor. Никакой реализации.
2. Read-only метаданные хоста: uid/gid/docker group/socket, занятость порта8765,
   существование каталога /home/user/services/ai-browser-gateway и только
   несекретных конфигов/метаданных. Чужие compose/env/docker inspect ENV не
   читать и не менять. Если сервис уже существует — описать и остановить
   предложения перезаписи. Не запускать/останавливать контейнеры сервисов.
3. Runtime image Python+Docker CLI: проверь актуальные stable версии и digest
   по первичным registry-источникам, совместимость с кодом и host daemon;
   минимальный поддерживаемый вариант без установки чего-либо на host.
   Локальные имеющиеся provider image IDs отдельно от проверенных registry pins.
   Поиски только первичные источники. Не скачивать/собирать большой образ сейчас.
4. Пул ms1..ms15: точный existing loader и выбор profile в M10/API, механизм
   чередования по запросам с сохранением ОДНОЙ фактической смены egress.
   Существующий источник credentials уже доказан: не читать значения сейчас,
   не создавать profiles. Для будущей спеки — безопасный программный parse
   только двух ключей PROXY_LOGIN/PROXY_PASSWORD, atomically0600 вне git.
   Предложи проверку15профилей с минимальной нагрузкой и строгим redaction.
5. Monitoring: прочитай локальный healthchecks-monitoring/SKILL.md по пути
   из service-monitoring-notes. Не создавать check и не делать ping/API вызов
   в разведке. Дай точный helper/interface и проверку периодического health
   loop + реальной pings history; management key не попадает в runtime.
6. Короткая матрица требований/проверок для M12: конфиг/права/loopback,
   health/auth, настоящий CLI→API→провайдер, global browser limit, proxy pool,
   автоматический monitoring, restart/release/rollback, all valid=true targets
   с budget и hostname gap>=30s. Отдели локальные негативные контроли от
   внешнего deployed-замера, не меняй challenge/expected_text правила.
   Нужен ли разрез M12a implementation / M12b deployment, чтобы каждый
   review diff<100000bytes и не более12AC? Только рекомендация с фактами.

Границы: исходники в клоне read-only, без pull/push/merge/commits, без правок
оснастки/продукта/tests, DNS/WAF/публичного443 и чужих рабочих деревьев.
Никаких sudo, host установок, секретов в stdout/argv/логах, .env глазами,
host tmux socket/kill-server/сигналов чужим процессам. Продукт исполнять только
Docker1002:1002; host Python допускается для оркестрации/метаданных. Пока не
делать внешние целевые запросы: это отдельный авторизованный deployed-прогон.
Короткий пакет: команды, cwd, rc, логи, SHA дерева/артефактов; каждый вывод
привязан к улике, неизвестное явно. Не писать report.json как реализацию,
не вызывать дополнительные ревьюеры или модели.
