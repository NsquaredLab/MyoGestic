import { mountSignalField, CONFIDENCE, type Gesture } from '../signal-field/index';

const hero = document.querySelector<HTMLElement>('.home-hero');
if (hero) {
    const prediction = hero.querySelector<HTMLElement>('[data-prediction]')!;
    const confidence = hero.querySelector<HTMLElement>('[data-confidence]')!;
    const confidenceBar = hero.querySelector<HTMLElement>('[data-confidence-bar]')!;
    const recordLabel = hero.querySelector<HTMLElement>('[data-record-label]')!;
    const chips = hero.querySelectorAll<HTMLButtonElement>('[data-gesture]');
    const auto = hero.querySelector<HTMLButtonElement>('[data-auto]')!;
    // The controller owns the surface and may replace it after context loss.
    // All subsequent UI work uses the controller or the enclosing hero.
    const controller = mountSignalField(hero.querySelector<HTMLCanvasElement>('[data-signal-field]')!, {
        onGesture(gesture, automatic) {
            prediction.textContent = gesture;
            confidence.textContent = CONFIDENCE[gesture].toFixed(2);
            confidenceBar.style.width = `${Math.round(CONFIDENCE[gesture] * 100)}%`;
            recordLabel.textContent = `Record ${gesture}`;
            for (const chip of chips) chip.setAttribute('aria-pressed', String(chip.dataset.gesture === gesture));
            auto.textContent = automatic ? 'Auto' : 'Auto off';
            auto.setAttribute('aria-pressed', String(automatic));
        },
    });
    for (const chip of chips) chip.addEventListener('click', () => controller.hold(chip.dataset.gesture as Gesture));
    auto.addEventListener('click', () => controller.auto());
    window.addEventListener('pagehide', event => {
        // A page in the back/forward cache resumes with its existing controller.
        if (!event.persisted) controller.destroy();
    });
    document.addEventListener('astro:before-swap', () => controller.destroy(), { once: true });
    document.addEventListener('keydown', event => {
        if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
            event.preventDefault();
            const search = hero.querySelector<HTMLAnchorElement>('a[aria-label^="Search"]');
            if (search) window.location.assign(search.href);
        }
    });
}

function copyButton(button: HTMLButtonElement | null, status: HTMLElement | null, value: string) {
    button?.addEventListener('click', async () => {
        if (!status) return;
        status.textContent = '';
        try {
            await navigator.clipboard.writeText(value);
            status.textContent = 'Copied';
        } catch {
            status.textContent = 'Copy failed. Please copy the text manually.';
        }
    });
}

copyButton(document.querySelector('[data-copy-install]'), document.querySelector('[data-install-status]'), 'pip install myogestic');
const bibtex = document.querySelector<HTMLButtonElement>('[data-copy-bibtex]');
copyButton(bibtex, document.querySelector('[data-cite-status]'), bibtex?.dataset.bibtex ?? '');
