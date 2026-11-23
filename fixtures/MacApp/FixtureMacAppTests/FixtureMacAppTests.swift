//
//  FixtureMacAppTests.swift
//  FixtureMacAppTests
//

@testable import FixtureMacApp
import Foundation
import Testing

struct FixtureMacAppTests {
    /// Configs/Project.xcconfig の MARKETING_VERSION が「x.y.z」形式で Info.plist に反映されていることを確認する
    @Test
    func marketingVersionIsSemanticVersion() throws {
        let version = try #require(
            Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String
        )
        let components = version.split(separator: ".")
        #expect(components.count == 3, "MARKETING_VERSION は x.y.z 形式で指定する: \(version)")
        #expect(components.allSatisfy { Int($0) != nil }, "各要素は整数で指定する: \(version)")
    }

    /// Mac App Store に要るカテゴリ（LSApplicationCategoryType）が Info.plist に入っていることを確認する
    @Test
    func applicationCategoryIsSet() throws {
        let category = try #require(
            Bundle.main.object(forInfoDictionaryKey: "LSApplicationCategoryType") as? String
        )
        #expect(category.hasPrefix("public.app-category."))
    }
}
