interface FocusTarget { focus(): void }

// A translation or refresh belongs to the same page. A result is a new page state.
export class PageFocus {
  #page: string | undefined
  #focused = false

  focus(page: string | null, target: FocusTarget | null, ready: boolean): boolean {
    if (page === null) return false // Loading does not replace the current semantic page.
    if (this.#page !== page) { this.#page = page; this.#focused = false }
    if (!ready || !target || this.#focused) return false
    this.#focused = true
    target.focus()
    return true
  }
}
