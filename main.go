package main

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"os"

	"github.com/cakeholeDC/on-air/cmd"
)

//go:embed .release-please-manifest.json
var releaseManifest []byte

func main() {
	var manifest struct {
		Version string `json:"."`
	}
	if err := json.Unmarshal(releaseManifest, &manifest); err != nil {
		fmt.Fprintln(os.Stderr, "Could not read the embedded release manifest.", err)
		os.Exit(1)
	}
	if manifest.Version == "" {
		fmt.Fprintln(os.Stderr, "The embedded release manifest is missing the OnAir version.")
		os.Exit(1)
	}

	cmd.Execute(manifest.Version)
}
