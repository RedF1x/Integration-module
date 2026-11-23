(() => {
    const root = document.getElementById("jira-backlog");
    if (!root) return;

    const sort = document.getElementById("backlog-sort");
        const reset = document.getElementById("backlog-reset");
    const filters = [
        ["status", document.getElementById("backlog-status")],
        ["type", document.getElementById("backlog-type")],
        ["assignee", document.getElementById("backlog-assignee")],
    ];
    const controls = [sort, reset, ...filters.map(([, element]) => element)];
    const message = document.getElementById("backlog-message");
    const login = document.getElementById("backlog-login");
    const retry = document.getElementById("backlog-retry");
    const updated = document.getElementById("backlog-updated");
    const list = document.getElementById("backlog-list");
    const pagination = document.getElementById("backlog-pagination");
    const pageLabel = document.getElementById("backlog-page");
    const previous = document.getElementById("backlog-prev");
    const next = document.getElementById("backlog-next");

    // Текущий API возвращает до 20 задач на странице.
    const pageSize = 20;
    let currentPage = 1;
    let loading = false;

    function makeElement(tag, text) {
        const element = document.createElement(tag);
        element.textContent = text;
        return element;
    }

    function makeCard(issue) {
        const card = document.createElement("article");
        card.className = "jira-task-card";

        const link = document.createElement("a");
        link.textContent = issue.key;
        link.href = root.dataset.issueUrlTemplate.replace(
            "ISSUEKEY",
            encodeURIComponent(issue.key)
        );
        card.appendChild(link);
        card.appendChild(makeElement("h3", issue.summary));
        card.appendChild(makeElement("p", `Статус: ${issue.status}`));
        card.appendChild(makeElement("p", `Тип: ${issue.issue_type}`));

        const assignee = issue.assignee?.display_name || "Не назначен";
        card.appendChild(makeElement("p", `Исполнитель: ${assignee}`));
        card.appendChild(
            makeElement("p", `Приоритет: ${issue.priority || "Не указан"}`)
        );

        return card;
    }

    async function loadBacklog(targetPage = 1) {
        if (loading) return;
        loading = true;
        controls.forEach(element => {
            element.disabled = true;
        });
        retry.hidden = true;
        login.hidden = true;
        pagination.hidden = true;
        list.replaceChildren();
        updated.textContent = "";
        message.textContent = "Загружаем задачи…";
        root.setAttribute("aria-busy", "true");

        try {
            const url = new URL(root.dataset.apiUrl, window.location.origin);
            url.searchParams.set("sort", sort.value);
            url.searchParams.set("page", String(targetPage));

            for (const [name, element] of filters) {
                if (element.value) {
                    url.searchParams.set(name, element.value);
                }
            }


            const response = await fetch(url, {
                credentials: "same-origin",
                headers: { Accept: "application/json" },
                cache: "no-store",
            });

            if (response.status === 401) {
                message.textContent = "Сессия закончилась. Войдите снова.";
                login.hidden = false;
                return;
            }

            if (response.status === 403) {
                message.textContent = "У вас нет доступа к бэклогу практиканта.";
                return;
            }

            if (response.status === 404) {
                message.textContent =
                    "Страница больше недоступна. Загрузите бэклог заново.";
                retry.hidden = false;
                return;
            }

            if (!response.ok) {
                throw new Error("Не удалось загрузить бэклог.");
            }

            const data = await response.json();
            const fragment = document.createDocumentFragment();

            for (const issue of data.results) {
                fragment.appendChild(makeCard(issue));
            }

            list.replaceChildren(fragment);
            currentPage = targetPage;

            message.textContent = data.count
                ? `Всего задач: ${data.count}`
                : "В бэклоге пока нет доступных задач.";

            if (data.synced_at) {
                const date = new Date(data.synced_at);
                if (!Number.isNaN(date.getTime())) {
                    updated.textContent =
                        `Данные обновлены: ${date.toLocaleString("ru-RU")}`;
                }
            }

            const totalPages = Math.max(1, Math.ceil(data.count / pageSize));
            pageLabel.textContent = `Страница ${currentPage} из ${totalPages}`;
            previous.disabled = currentPage <= 1;
            next.disabled = currentPage >= totalPages;
            pagination.hidden = data.count === 0;
        } catch {
            list.replaceChildren();
            updated.textContent = "";
            pagination.hidden = true;
            message.textContent =
                "Не удалось загрузить задачи. Попробуйте ещё раз.";
            retry.hidden = false;
        } finally {
            loading = false;
            controls.forEach(element => {
                element.disabled = false;
            });
            root.setAttribute("aria-busy", "false");
        }
    }

    sort.addEventListener("change", () => loadBacklog(1));
    previous.addEventListener("click", () => loadBacklog(currentPage - 1));
    next.addEventListener("click", () => loadBacklog(currentPage + 1));
    retry.addEventListener("click", () => loadBacklog(1));

    for (const [, element] of filters) {
        element.addEventListener("change", () => loadBacklog(1));
    }

    reset.addEventListener("click", () => {
        for (const [, element] of filters) {
            element.value = "";
        }
        loadBacklog(1);
    });

    loadBacklog();
})();