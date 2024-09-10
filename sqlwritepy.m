% sqlwrite function
function sqlwritepy(dbpath, tableName, T)
py.sqlite_append.sql_append(tableName, T, dbpath);
end