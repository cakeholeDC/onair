package main

import (
	"encoding/json"
	"flag"
	"os"
	"os/exec"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestVersionFlags(t *testing.T) {
	if args := flag.Args(); len(args) == 2 && args[0] == "onair-version" {
		os.Args = []string{"onair", args[1]}
		main()
		os.Exit(0)
	}

	manifest, err := os.ReadFile(".release-please-manifest.json")
	require.NoError(t, err)
	var versions map[string]string
	require.NoError(t, json.Unmarshal(manifest, &versions))
	require.NotEmpty(t, versions["."])

	for _, versionFlag := range []string{"-v", "--version"} {
		t.Run(versionFlag, func(t *testing.T) {
			command := exec.Command(os.Args[0], "-test.run=^TestVersionFlags$", "--", "onair-version", versionFlag)
			command.Dir = t.TempDir()
			output, err := command.CombinedOutput()
			require.NoError(t, err, string(output))
			require.Equal(t, "onair version "+versions["."]+"\n", string(output))
		})
	}
}
