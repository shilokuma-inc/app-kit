//
//  FixtureMacWidget.swift
//  FixtureMacWidget
//

import SwiftUI
import WidgetKit

struct FixtureEntry: TimelineEntry {
    let date: Date
}

struct FixtureProvider: TimelineProvider {
    func placeholder(in context: Context) -> FixtureEntry {
        FixtureEntry(date: .now)
    }

    func getSnapshot(in context: Context, completion: @escaping (FixtureEntry) -> Void) {
        completion(FixtureEntry(date: .now))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<FixtureEntry>) -> Void) {
        completion(Timeline(entries: [FixtureEntry(date: .now)], policy: .never))
    }
}

@main
struct FixtureMacWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "FixtureMacWidget", provider: FixtureProvider()) { entry in
            Text(entry.date, style: .time)
                .containerBackground(.fill, for: .widget)
        }
    }
}
