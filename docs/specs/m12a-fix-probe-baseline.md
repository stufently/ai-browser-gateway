# Frozen M12 service regressions

BASE: `62de539f586b95e6aeb971c3ab1f51e6f7080260`. Probe SHA256: `f7ab236f81fccdddf5fd9df9611b9a2f3f3f33dd3162865c083a22a8d569ecad`.

Запуск из корня checkout:

```sh
docker run --rm --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -v tests.probe_m12_service_regressions
```

BASE: rc=1, 5 методов, 5 assertion failures: ожидающий browser-slot запрос
запускает provider после SIGTERM; уже допущенный Docker launch оставляет
позднего provider; make_service принимает proxy U+00A0 и U+0085;
prepare CLI принимает symlink manifests/<sha>.sha256. Default M11 контроль green.
Ошибок import/fixture/среды нет. Контракт: docs/specs/m12a-service-contract.md.
Тест использует настоящий HTTP/entrypoint/лестницу/semaphore/DockerLauncher,
фейки только на Docker subprocess IO. Все процессы/сигналы внутри Docker;
Docker socket и внешние цели не нужны. Watchdog относится только к стенду.

Передавать исполнителю только этот summary и byte-identical probe.
