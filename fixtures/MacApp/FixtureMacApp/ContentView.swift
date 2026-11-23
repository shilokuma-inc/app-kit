//
//  ContentView.swift
//  FixtureMacApp
//

import SwiftUI

struct ContentView: View {
    var body: some View {
        VStack {
            Image(systemName: "macwindow")
                .imageScale(.large)
                .foregroundStyle(.tint)
            Text("Hello, world!")
                .accessibilityIdentifier("greeting")
        }
        .padding()
        .frame(minWidth: 320, minHeight: 200)
    }
}

#Preview {
    ContentView()
}
