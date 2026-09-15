# M12a — предпусковые команды на BASE, только подготовка

Исполнитель явный Grok. Клон /home/user/exec-clones/abg-m12a-service-20260915,
ветка m12a-service, BASE_SHA 7ca38c1aa62174a0a1de1a7685fee268c2ba2042.
Обновлённая директива владельца15.09 разрешила продолжение; старый HOLD снят.
Это НЕ реализация. Код, tests, spec, report.json и HEAD не менять/не коммитить.
В клоне два доставленных untracked: docs/specs/m12a-service.md и
 tests/probe_m12_service.py. Их ожидаемое наличие не «грязная чужая работа».

Прочитать docs/specs/m12a-service.md и выполнить ТОЧНЫЕ шесть команд критериев
на текущем BASE. Сохранить для каждой command/cwd/rc/полный безопасный log.
Ожидаемые исходы: AC-301 pass (413unit), AC-302 red20missing-public-API нового
M12probe при green прежних frozen probes; AC-303 redmissing tests/live_m12_service.py;
AC-304 pass; AC-305 redmissingrequired new service files; AC-306 pass.
Отличать rc команды от rc обёртки, не глушить ||true/echo; реальные ошибки
Docker/прав/хешей/синтаксиса не считать ожидаемым red. Не исправлять продукт.

Перед командами: сверить BASE_SHA, exactspec SHA с копией
/home/user/github/ai-browser-gateway/docs/specs/m12a-service.md и frozenprobe
SHA2562b5713ea3d3b743a6c469bd26bd893cb343f132b83deb7eadc6182e007ad71e0.
Не читать эталоны/обходы/приватный контекст cx-подготовки. Они уже приняты,
повторять их не нужно. Не повторять разведку/бенчмарки/M9-M11live.

Дополнительно сохранить безопасный precheck доступности exactimages из
speccontract (docker inspect только Id/RepoDigests, не ENV). Новые образы
не собирать/скачивать. На пропавшем образе дать конкретный blocker.

Выход /home/user/.cache/abg-coord-20260915/m12/preflight/result.md,
logs/, commands.json, SHA256SUMS с путями относительно каталога пакета.
Итог каждой команды сопоставить ожидаемому; после завершения подтверждение
HEAD/spec/probe unchanged, только исходные2untracked; новых контейнеров нет.
После пакета остановиться: реализацию запустит координатор отдельным заданием.

Все tests/import/assertions продукта в Docker1002:1002; host Python только
оркестрация/meta. Никаких sudo/host installs/секретов/.env/чужих trees/services,
host tmux socket/сигналов/публичного443/DNS/WAF. Push/merge/deploy запрещены.
Не вызывать моделей/reviewers. Spark до20.09 15:59исчерпан, gkwindows неизвестны;
quota error сохранить и остановиться, не повторять ради квоты.
