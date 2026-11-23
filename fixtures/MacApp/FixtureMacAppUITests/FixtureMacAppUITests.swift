//
//  FixtureMacAppUITests.swift
//  FixtureMacAppUITests
//

import XCTest

final class FixtureMacAppUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    @MainActor
    func testLaunchShowsGreeting() throws {
        let app = XCUIApplication()
        app.launch()

        XCTAssertTrue(app.staticTexts["greeting"].waitForExistence(timeout: 10))
    }
}
