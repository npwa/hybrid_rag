## A few more comments so far

1. Need to add files with `.md` extensions to the whitelist. No conversion should be
   done. However, I wonder if it's ok to leave the extension as `.md` instead of ingesting
   the file as `.md.txt` - Explain if the `.txt` extension is required
   
2. TODO files should be treated in the same way as README files, same pattern matching,
   same processing with `convert_to_md.sh`

3. Add a tags column to the manifest schema and parse any file that goes through the
   `convert_to_md.sh` conversion path accordingly.

4. For example, `README.txt` files should be processed with `convert_to_md.sh` but the
   resulting filename should be `README.md` and not `README.txt.txt` (unless there is a
   clash with an additional original README file, in which case the second occurrence
   should be named `README-2.md`)
