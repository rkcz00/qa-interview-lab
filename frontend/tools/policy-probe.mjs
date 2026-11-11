import { passwordIssues } from '../src/auth/validation.ts'

let input = ''
for await (const chunk of process.stdin) input += chunk
const cases = JSON.parse(input)
process.stdout.write(JSON.stringify(cases.map(({ email, password }) => passwordIssues(email, password))))
