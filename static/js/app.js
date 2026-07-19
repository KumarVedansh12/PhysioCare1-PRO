(function () {
    "use strict";

    function refreshIcons() {
        if (window.lucide) window.lucide.createIcons({ attrs: { "aria-hidden": "true" } });
    }

    refreshIcons();

    const sidebar = document.getElementById("portal-sidebar");
    document.querySelectorAll("[data-sidebar-toggle]").forEach((button) => {
        button.addEventListener("click", () => {
            if (!sidebar) return;
            sidebar.classList.toggle("open");
            document.body.classList.toggle("no-scroll", sidebar.classList.contains("open"));
        });
    });

    const publicMenu = document.querySelector("[data-public-nav]");
    const publicMenuButton = document.querySelector("[data-public-menu]");
    if (publicMenu && publicMenuButton) {
        publicMenuButton.addEventListener("click", () => publicMenu.classList.toggle("open"));
        publicMenu.querySelectorAll("a").forEach((link) => link.addEventListener("click", () => publicMenu.classList.remove("open")));
    }

    document.querySelectorAll("[data-tabs]").forEach((tabsRoot) => {
        const buttons = tabsRoot.querySelectorAll("[data-tab]");
        const items = tabsRoot.querySelectorAll("[data-tab-item]");
        const select = (name) => {
            buttons.forEach((button) => button.classList.toggle("active", button.dataset.tab === name));
            items.forEach((item) => { item.hidden = item.dataset.tabItem !== name; });
        };
        buttons.forEach((button) => button.addEventListener("click", () => select(button.dataset.tab)));
        if (buttons.length) select(buttons[0].dataset.tab);
    });

    document.querySelectorAll("[data-modal-open]").forEach((button) => {
        button.addEventListener("click", () => {
            const modal = document.getElementById(button.dataset.modalOpen);
            if (!modal) return;
            modal.classList.add("open");
            modal.setAttribute("aria-hidden", "false");
            document.body.classList.add("no-scroll");
            const focusTarget = modal.querySelector("input, select, textarea, button");
            if (focusTarget) setTimeout(() => focusTarget.focus(), 50);
        });
    });

    document.querySelectorAll("[data-modal-close]").forEach((button) => {
        button.addEventListener("click", () => {
            const modal = button.closest(".modal");
            if (!modal) return;
            modal.classList.remove("open");
            modal.setAttribute("aria-hidden", "true");
            document.body.classList.remove("no-scroll");
        });
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            document.querySelectorAll(".modal.open").forEach((modal) => {
                modal.classList.remove("open");
                modal.setAttribute("aria-hidden", "true");
            });
            document.body.classList.remove("no-scroll");
        }
    });

    document.querySelectorAll("[data-accordion] article button").forEach((button) => {
        button.addEventListener("click", () => button.closest("article").classList.toggle("open"));
    });

    document.querySelectorAll(".password-toggle").forEach((button) => {
        button.addEventListener("click", () => {
            const input = button.parentElement.querySelector("input");
            if (!input) return;
            input.type = input.type === "password" ? "text" : "password";
            button.innerHTML = `<i data-lucide="${input.type === "password" ? "eye" : "eye-off"}"></i>`;
            refreshIcons();
        });
    });

    document.querySelectorAll("[data-media-toggle]").forEach((button) => {
        button.addEventListener("click", () => {
            const isOff = button.classList.toggle("off");
            const type = button.dataset.mediaToggle;
            button.innerHTML = `<i data-lucide="${isOff ? `${type}-off` : type}"></i><span>${type === "audio" ? "Microphone" : "Camera"}</span>`;
            refreshIcons();
        });
    });

    const joinButton = document.querySelector("[data-join-call]");
    if (joinButton) {
        joinButton.addEventListener("click", () => {
            joinButton.innerHTML = '<i data-lucide="loader-circle"></i> Connecting securely…';
            joinButton.disabled = true;
            refreshIcons();
            setTimeout(() => {
                joinButton.innerHTML = '<i data-lucide="phone-off"></i> End consultation';
                joinButton.disabled = false;
                joinButton.classList.add("btn-danger");
                refreshIcons();
            }, 1200);
        });
    }

    const voiceButton = document.querySelector("[data-voice-button]");
    if (voiceButton) {
        voiceButton.addEventListener("click", () => {
            voiceButton.classList.toggle("voice-recording");
            voiceButton.title = voiceButton.classList.contains("voice-recording") ? "Recording — tap to stop" : "Record a voice message";
        });
    }

    document.querySelectorAll(".filter-pills").forEach((group) => {
        group.querySelectorAll("button").forEach((button) => button.addEventListener("click", () => {
            group.querySelectorAll("button").forEach((item) => item.classList.remove("active"));
            button.classList.add("active");
        }));
    });

    document.querySelectorAll("[data-table-search]").forEach((input) => {
        const target = document.getElementById(input.dataset.tableSearch);
        if (!target) return;
        input.addEventListener("input", () => {
            const query = input.value.trim().toLowerCase();
            target.querySelectorAll("[data-search-row]").forEach((row) => {
                row.hidden = Boolean(query) && !row.textContent.toLowerCase().includes(query);
            });
        });
    });

    document.querySelectorAll("[data-focus-search]").forEach((link) => {
        link.addEventListener("click", () => {
            const input = document.getElementById(link.dataset.focusSearch);
            if (input) setTimeout(() => input.focus(), 150);
        });
    });

    const messageList = document.getElementById("message-list");
    if (messageList) messageList.scrollTop = messageList.scrollHeight;

    document.querySelectorAll(".toast-message").forEach((toast) => {
        setTimeout(() => toast.remove(), 6500);
    });
})();
