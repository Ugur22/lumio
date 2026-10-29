// Runs against `make e2e-server`; the stub's reply is chosen by a [[fake:NAME]] marker in the message.
function send(text: string) {
  cy.get('textarea[aria-label="Message"]').type(text);
  cy.get('button[aria-label="Send"]').click();
}

describe("smoke journey", () => {
  beforeEach(() => {
    cy.visit("/");
  });

  it("streams the stub reply for a plain message", () => {
    send("hello");
    cy.contains("Hello from the fake upstream.").should("be.visible");
  });

  it("shows the error state when the upstream fails", () => {
    send("boom [[fake:error]]");
    cy.get('[role="alert"]').should("contain.text", "fake upstream failure");
    cy.get('textarea[aria-label="Message"]').should("be.visible");
  });

  it("runs a JavaScript code block and shows its output", () => {
    send("show code [[fake:code]]");
    cy.get('button[aria-label="Run JavaScript code"]').click();
    cy.get('[role="region"][aria-label="Output"]', { timeout: 20000 }).should("contain.text", "fake-code-output");
  });
});
