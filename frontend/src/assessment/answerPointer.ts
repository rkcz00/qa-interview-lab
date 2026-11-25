type PointerActivation = Pick<MouseEvent, 'type' | 'detail' | 'preventDefault' | 'stopPropagation'>

// The second press can hit a different element after the question changes height.
export class AnswerPointerGuard {
  #advanced = false

  afterAnswer(advanced: boolean, detail: number) {
    this.#advanced = advanced && detail === 1
  }

  cancelRepeated(event: PointerActivation): boolean {
    if (!['mousedown', 'click', 'dblclick'].includes(event.type)) return false
    if (event.type === 'mousedown' && event.detail <= 1) this.#advanced = false
    if (!this.#advanced || event.detail <= 1) return false
    event.preventDefault()
    event.stopPropagation()
    return true
  }
}
