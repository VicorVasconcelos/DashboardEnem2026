(function () {
    const getSafeDocument = () => {
        try {
            if (window.parent && window.parent.document) {
                return window.parent.document;
            }
        } catch (error) {
            return document;
        }
        return document;
    };

    const doc = getSafeDocument();
    if (!doc.querySelector('[data-testid="stAppViewContainer"]')) {
        return;
    }

    const applyEnhancements = () => {
        const localDoc = getSafeDocument();

        const main = localDoc.querySelector('[data-testid="stAppViewContainer"]');
        if (main) {
            main.classList.add('enem-enhanced');
        }

        const h3Nodes = Array.from(localDoc.querySelectorAll('h3'));
        h3Nodes.forEach((node) => {
            if (node.textContent && node.textContent.trim().toLowerCase() === 'filtros') {
                const wrapper = node.closest('[data-testid="element-container"]');
                if (wrapper) {
                    wrapper.classList.add('enem-filter-anchor');
                }
            }
        });
    };

    applyEnhancements();

    const observer = new MutationObserver(() => applyEnhancements());
    observer.observe(doc.body, { childList: true, subtree: true });
})();
