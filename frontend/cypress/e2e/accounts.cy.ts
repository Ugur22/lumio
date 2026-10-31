// The e2e server is not deployed, so the real /api/auth/me answers with the fixed local user. These specs stub
// /api/auth/* to play a deployed server: the rest of the app still talks to the stub upstream.
const alice = { id: "u1", username: "alice", is_admin: false };

describe("accounts", () => {
  it("signs in, uses the app, and signs out", () => {
    cy.intercept("GET", "/api/auth/me", { statusCode: 401, body: { detail: "Not signed in" } });
    cy.intercept("POST", "/api/auth/login", { statusCode: 200, body: alice }).as("login");
    cy.intercept("POST", "/api/auth/logout", { statusCode: 204 }).as("logout");

    cy.visit("/");
    cy.get('textarea[aria-label="Message"]').should("not.exist");

    cy.get('input[name="username"]').type("Alice");
    cy.get('input[name="password"]').type("correct horse battery{enter}");
    cy.wait("@login").its("request.body").should("deep.equal", { username: "alice", password: "correct horse battery" });

    cy.get('textarea[aria-label="Message"]').type("hello");
    cy.get('button[aria-label="Send"]').click();
    cy.contains("Hello from the fake upstream.").should("be.visible");

    cy.contains("button", "alice").click();
    cy.contains('[role="menuitem"]', "Sign out").click();
    cy.wait("@logout");
    cy.get('[role="tab"]').contains("Sign in").should("be.visible");
    cy.get('textarea[aria-label="Message"]').should("not.exist");
  });

  it("shows the server's message for a wrong password", () => {
    cy.intercept("GET", "/api/auth/me", { statusCode: 401, body: { detail: "Not signed in" } });
    cy.intercept("POST", "/api/auth/login", { statusCode: 401, body: { detail: "Invalid username or password" } });
    cy.visit("/");
    cy.get('input[name="username"]').type("alice");
    cy.get('input[name="password"]').type("wrong-password{enter}");
    cy.get('[role="alert"]').should("contain.text", "Invalid username or password");
  });

  it("never shows the login screen for the local user", () => {
    cy.visit("/");
    cy.get('textarea[aria-label="Message"]').should("be.visible");
    cy.get('[role="tab"]').should("not.exist");
    cy.contains("button", "Sign out").should("not.exist");
  });
});
