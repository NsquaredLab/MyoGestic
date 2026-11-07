import { mountSignalField, CONFIDENCE, type Gesture } from '../signal-field/index';

const hero = document.querySelector<HTMLElement>('.home-hero');
if (hero) {
    const copy = hero.querySelector<HTMLElement>('.hero-copy')!;
    const panels = hero.querySelector<HTMLElement>('[data-panels]')!;
    // Track layout changes (including font loading), outside the field's frame
    // loop. These offsets also survive the controller replacing a lost canvas.
    const alignField = () => {
        const bounds = hero.getBoundingClientRect();
        const headline = copy.getBoundingClientRect();
        const instruments = panels.getBoundingClientRect();
        hero.style.setProperty('--hero-field-top', `${instruments.top - bounds.top}px`);
        hero.style.setProperty('--hero-probe-x', `${(headline.right + instruments.left) / 2 - bounds.left}px`);
    };
    alignField();
    const layout = new ResizeObserver(alignField);
    for (const element of [hero, copy, panels]) layout.observe(element);
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
    const destroy = () => {
        layout.disconnect();
        controller.destroy();
    };
    window.addEventListener('pagehide', event => {
        // A page in the back/forward cache resumes with its existing controller.
        if (!event.persisted) destroy();
    });
    document.addEventListener('astro:before-swap', destroy, { once: true });
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
