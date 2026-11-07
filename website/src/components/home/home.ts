import { mountSignalFieldAfterLoad, CONFIDENCE, type Gesture } from '../signal-field/index';

const hero = document.querySelector<HTMLElement>('.home-hero');
if (hero) {
    const copy = hero.querySelector<HTMLElement>('.hero-copy')!;
    const panels = hero.querySelector<HTMLElement>('[data-panels]')!;
    // Track layout changes (including font loading), outside the field's frame
    // loop. These offsets also survive the controller replacing a lost canvas.
    const alignField = () => {
        const bounds = hero.getBoundingClientRect();
        const instruments = panels.getBoundingClientRect();
        hero.style.setProperty('--hero-field-top', `${instruments.top - bounds.top}px`);
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
    const controller = mountSignalFieldAfterLoad(hero.querySelector<HTMLCanvasElement>('[data-signal-field]')!, {
        onGesture(gesture, automatic) {
            prediction.textContent = gesture;
            confidence.textContent = CONFIDENCE[gesture].toFixed(2);
            confidenceBar.style.width = `${Math.round(CONFIDENCE[gesture] * 100)}%`;
            recordLabel.textContent = gesture;
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

function copyButton(button: HTMLButtonElement | null, status: HTMLElement | null, value: string, showOnButton = false) {
    button?.addEventListener('click', async () => {
        if (!status) return;
        status.textContent = '';
        try {
            await navigator.clipboard.writeText(value);
            status.textContent = 'Copied';
            if (showOnButton) button.textContent = 'Copied';
        } catch {
            status.textContent = 'Copy failed. Please copy the text manually.';
        }
    });
}

copyButton(document.querySelector('[data-copy-install]'), document.querySelector('[data-install-status]'), 'pip install myogestic');
const bibtex = document.querySelector<HTMLButtonElement>('[data-copy-bibtex]');
copyButton(bibtex, document.querySelector('[data-cite-status]'), bibtex?.dataset.bibtex ?? '');
for (const button of document.querySelectorAll<HTMLButtonElement>('[data-copy-command]')) {
    const status = button.closest('article')?.querySelector<HTMLElement>('[data-command-status]') ?? null;
    copyButton(button, status, button.dataset.command ?? '', true);
}

// Hello EMG: pointing at a code group lights up what it builds in the screenshot,
// and pointing at part of the screenshot lights up its code.
const hello = document.querySelector<HTMLElement>('[data-hello]');
if (hello) {
    const regions = JSON.parse(hello.dataset.regions ?? '{}') as Record<string, { x: number; y: number; w: number; h: number; label: string }>;
    const spot = hello.querySelector<HTMLElement>('[data-spot]')!;
    const label = spot.querySelector<HTMLElement>('[data-spot-label]')!;
    const lines = hello.querySelectorAll<HTMLElement>('.hello-line[data-link]');
    const show = (id: string | null) => {
        const region = id ? regions[id] : undefined;
        if (!region) {
            delete hello.dataset.active;
            spot.hidden = true;
        } else {
            hello.dataset.active = id!;
            spot.style.left = `${region.x}%`;
            spot.style.top = `${region.y}%`;
            spot.style.width = `${region.w}%`;
            spot.style.height = `${region.h}%`;
            label.textContent = region.label;
            spot.hidden = false;
        }
        for (const line of lines) line.classList.toggle('is-active', line.dataset.link === id);
    };
    for (const el of hello.querySelectorAll<HTMLElement>('[data-link]')) {
        const id = el.dataset.link!;
        el.addEventListener('pointerenter', () => show(id));
        // A tap on a phone keeps the highlight; only a mouse leaving clears it.
        el.addEventListener('pointerleave', (event) => { if (event.pointerType === 'mouse') show(null); });
        el.addEventListener('focus', () => show(id));
        el.addEventListener('blur', () => show(null));
        el.addEventListener('click', () => show(id));
    }
    hello.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
            (document.activeElement as HTMLElement | null)?.blur();
            show(null);
        }
    });
}
