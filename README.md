    # SigmaOS-system-admin

    System administration toolkit (services, disks, logs)

    Part of the **SigmaOS** sovereign operating-system ecosystem — a multi-repository
    distribution modelled on Linux Mint and Omarchy Linux. See the parent
    [`SigmaOS`](https://github.com/AaryanSinghChauhan09/SigmaOS) repository for the
    full component index.

    ## Upstream inspirations
    - https://github.com/linuxmint/mintsysadm

    ## Design principles applied
    - **Pure Parsing**
- **Fail-Fast**
- **Least Astonishment**
- **KISS**
- **Deterministic Testing**

    ## Usage
    Verbs: `services, disks, logs, users, uptime-plan`

    ```
    $ sigma-sysadmin services --input systemctl.txt --state failed
$ sigma-sysadmin disks --input df.txt --threshold 90
$ sigma-sysadmin logs --input journal.txt --priority err --since 09:00
$ sigma-sysadmin users --input passwd.txt --shadow shadow.txt
$ sigma-sysadmin uptime-plan --reboot-required --pending-upgrades 12

    ```

    ## Build & test
    ```
    make build
    make test
    ```

    ## Licence
    GNU General Public License v3.0 (FOSS).
